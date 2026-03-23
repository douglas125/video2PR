#!/usr/bin/env python3
"""Detect GPU hardware and CTranslate2 device availability for faster-whisper.

Outputs structured JSON to stdout. Also exposes a check_gpu() function
for programmatic use.
"""

import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


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

    Returns (installed, cuda_available).
    """
    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types("cuda")
        return True, len(supported) > 0
    except (ImportError, RuntimeError, Exception):
        try:
            import ctranslate2
            return True, False
        except ImportError:
            return False, False


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
    ct2_installed, ct2_cuda = _check_ctranslate2_cuda()

    # Determine device and availability
    if ct2_cuda and gpu_name:
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
        "gpu_available": gpu_available,
        "install_command": install_command,
        "message": msg,
    }


def main():
    result = check_gpu()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
