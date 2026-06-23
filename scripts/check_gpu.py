#!/usr/bin/env python3
"""Detect GPU hardware and CTranslate2 device availability for faster-whisper.

Outputs structured JSON to stdout. Also exposes a check_gpu() function
for programmatic use.
"""

import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diagnostics import (  # noqa: E402
    PYTHON_EXCEPTION_MARKER,
    classify_worker_failure,
    collect_cuda_diagnostics,
    tail_text,
)


def _find_nvidia_smi():
    """Find the nvidia-smi executable path, with Windows fallback.

    Returns the path string or None.
    """
    exe = shutil.which("nvidia-smi")
    if exe is None and platform.system() == "Windows":
        fallback = r"C:\Windows\System32\nvidia-smi.exe"
        if Path(fallback).exists():
            exe = fallback
    return exe


def _run_nvidia_smi_query():
    """Query nvidia-smi for GPU name and driver version.

    Returns (gpu_name, driver_version) or (None, None) on failure.
    """
    exe = _find_nvidia_smi()
    if exe is None:
        return None, None

    try:
        result = subprocess.run(
            [exe, "--query-gpu=name,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None, None
        line = result.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return None, None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, None


def _parse_cuda_version():
    """Parse CUDA version from nvidia-smi header output.

    Returns version string like "12.4" or None.
    """
    exe = _find_nvidia_smi()
    if exe is None:
        return None

    try:
        result = subprocess.run(
            [exe],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.split("\n"):
            match = re.search(r"CUDA Version:\s+([\d.]+)", line)
            if match:
                return match.group(1)
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _check_ctranslate2_cuda():
    """Check if CTranslate2 (used by faster-whisper) supports CUDA.

    Returns (installed, cuda_available, supported_compute_types).
    """
    try:
        import ctranslate2

        supported = ctranslate2.get_supported_compute_types("cuda")
        return True, len(supported) > 0, sorted(supported)
    except (ImportError, RuntimeError, Exception):
        try:
            import ctranslate2  # noqa: F401

            return True, False, []
        except ImportError:
            return False, False, []


def _write_smoke_wav(path: Path) -> None:
    """Write a tiny 16 kHz mono WAV for CUDA inference smoke tests."""
    sample_rate = 16000
    duration_seconds = 1
    nframes = sample_rate * duration_seconds
    silence = b"\x00\x00" * nframes
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(silence)


def _run_cuda_inference_smoke_test(
    model_name: str = "tiny",
    compute_type: str = "float16",
    timeout_seconds: int = 120,
) -> dict:
    """Run a real CUDA faster-whisper inference in a child process."""
    fd, audio_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    audio_path = Path(audio_name)
    script = f"""
import faulthandler
import sys
import traceback

faulthandler.enable(all_threads=True)
try:
    from faster_whisper import WhisperModel

    print("SMOKE before model load", flush=True)
    model = WhisperModel(sys.argv[1], device="cuda", compute_type=sys.argv[3])
    print("SMOKE after model load", flush=True)
    segments, info = model.transcribe(sys.argv[2], beam_size=1, vad_filter=False)
    print("SMOKE after transcribe call", flush=True)
    for _ in segments:
        break
    print("SMOKE_OK", flush=True)
except BaseException as exc:
    print("{PYTHON_EXCEPTION_MARKER}: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr, flush=True)
    traceback.print_exc()
    sys.exit(1)
"""
    try:
        _write_smoke_wav(audio_path)
        result = subprocess.run(
            [sys.executable, "-c", script, model_name, str(audio_path), compute_type],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        ok = result.returncode == 0 and "SMOKE_OK" in (result.stdout or "")
        failure_class = None
        if not ok:
            failure_class = classify_worker_failure(
                result.returncode,
                result.stdout or "",
                result.stderr or "",
            )
        return {
            "ok": ok,
            "model": model_name,
            "compute_type": compute_type,
            "returncode": result.returncode,
            "failure_class": failure_class,
            "stdout_tail": tail_text(result.stdout, 2000),
            "stderr_tail": tail_text(result.stderr, 2000),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return {
            "ok": False,
            "model": model_name,
            "compute_type": compute_type,
            "returncode": 124,
            "failure_class": "timeout",
            "stdout_tail": tail_text(stdout, 2000),
            "stderr_tail": tail_text(stderr, 2000),
        }
    finally:
        with contextlib.suppress(OSError):
            Path(audio_name).unlink(missing_ok=True)


def check_gpu():
    """Detect GPU hardware and CTranslate2 device status.

    Returns a dict with detection results.
    """
    plat = platform.system()
    arch = platform.machine()

    # Detect NVIDIA GPU
    gpu_name, _ = _run_nvidia_smi_query()
    cuda_version = _parse_cuda_version() if gpu_name else None

    # Detect Apple Silicon
    is_apple_silicon = plat == "Darwin" and arch == "arm64"

    # Check CTranslate2 (faster-whisper backend)
    ct2_installed, ct2_cuda, ct2_supported = _check_ctranslate2_cuda()
    smoke = {
        "ok": False,
        "skipped": True,
        "reason": "No NVIDIA GPU with CTranslate2 CUDA support detected",
    }
    if gpu_name and ct2_cuda:
        smoke = _run_cuda_inference_smoke_test()

    # Determine device and availability
    if ct2_cuda and gpu_name and smoke.get("ok"):
        device = "cuda"
        gpu_available = True
    else:
        device = "cpu"
        gpu_available = False

    # Build install guidance if GPU exists but CTranslate2 can't use CUDA
    install_command = None
    if gpu_name and not ct2_cuda:
        # NVIDIA GPU present but CTranslate2 lacks CUDA support
        # This typically means CUDA toolkit needs to be installed
        install_command = "pip install --upgrade ctranslate2"

    # Build message
    if device == "cuda":
        msg = f"GPU acceleration: {gpu_name} via CUDA {cuda_version or 'unknown'}"
    elif gpu_name and ct2_cuda:
        msg = (
            f"GPU detected ({gpu_name}) and CTranslate2 reports CUDA support, "
            "but CUDA inference smoke test failed"
        )
    elif gpu_name:
        msg = f"GPU detected ({gpu_name}) but CUDA not available for CTranslate2"
    elif is_apple_silicon:
        msg = "Apple Silicon detected — faster-whisper uses CPU (CTranslate2 optimized)"
    else:
        msg = "Running on CPU (no GPU detected)"

    return {
        "platform": plat,
        "arch": arch,
        "device": device,
        "gpu_name": gpu_name,
        "cuda_version": cuda_version,
        "ct2_installed": ct2_installed,
        "ct2_cuda_supported": ct2_cuda,
        "ct2_supported_compute_types": ct2_supported,
        "cuda_inference_usable": bool(smoke.get("ok")),
        "cuda_smoke_test": smoke,
        "diagnostics": collect_cuda_diagnostics(
            device="cuda" if gpu_name and ct2_cuda else "cpu",
            compute_type="float16" if gpu_name and ct2_cuda else "int8",
            model_name=smoke.get("model", "tiny"),
            operation="gpu_check_smoke_test",
        ),
        "gpu_available": gpu_available,
        "install_command": install_command,
        "message": msg,
    }


def main():
    result = check_gpu()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
