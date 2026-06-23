"""Runtime diagnostics shared by video2pr command-line scripts."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

PYTHON_EXCEPTION_MARKER = "VIDEO2PR_PYTHON_EXCEPTION"

CUDA_PACKAGE_NAMES = [
    "faster-whisper",
    "ctranslate2",
    "nvidia-cublas-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cuda-nvrtc-cu12",
]


def tail_text(text: str | None, limit: int = 4000) -> str:
    """Return the tail of text for compact diagnostics."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return "...<truncated>...\n" + text[-limit:]


def format_exit_code(returncode: int | None) -> str:
    """Format a subprocess return code, including Windows native status codes."""
    if returncode is None:
        return "unknown"
    if returncode < 0:
        unsigned = returncode + (1 << 32)
        return f"{returncode} (0x{unsigned:08X})"
    if returncode > 255:
        signed = returncode - (1 << 32) if returncode >= (1 << 31) else returncode
        if signed != returncode:
            return f"{returncode} (0x{returncode:08X}, signed {signed})"
        return f"{returncode} (0x{returncode:08X})"
    return str(returncode)


def classify_worker_failure(
    returncode: int | None,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
) -> str:
    """Classify a CUDA worker failure."""
    if timed_out:
        return "timeout"
    combined = f"{stdout}\n{stderr}"
    if PYTHON_EXCEPTION_MARKER in combined or "Traceback (most recent call last)" in combined:
        return "python_exception"
    if returncode not in (None, 0):
        return "native_crash"
    return "inference_failed"


def find_nvidia_smi() -> str | None:
    """Find nvidia-smi, including the common Windows system path."""
    exe = shutil.which("nvidia-smi")
    if exe is None and platform.system() == "Windows":
        fallback = r"C:\Windows\System32\nvidia-smi.exe"
        if Path(fallback).exists():
            exe = fallback
    return exe


def query_nvidia_smi() -> dict:
    """Return GPU, driver, and reported CUDA version from nvidia-smi when available."""
    exe = find_nvidia_smi()
    if exe is None:
        return {"available": False}

    info: dict = {"available": True, "path": exe}
    try:
        result = subprocess.run(
            [exe, "--query-gpu=name,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        info["query_returncode"] = result.returncode
        if result.returncode == 0:
            line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                info["gpu_name"] = parts[0]
                info["driver_version"] = parts[1]
        else:
            info["query_stderr"] = tail_text(result.stderr, 1000)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    try:
        header = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        info["header_returncode"] = header.returncode
        if header.returncode == 0:
            match = re.search(r"CUDA Version:\s+([\d.]+)", header.stdout)
            if match:
                info["cuda_version"] = match.group(1)
        else:
            info["header_stderr"] = tail_text(header.stderr, 1000)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        info["header_error"] = f"{type(exc).__name__}: {exc}"

    return info


def package_versions() -> dict[str, str | None]:
    """Return relevant package versions without requiring every package to be installed."""
    versions = {}
    for package in CUDA_PACKAGE_NAMES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def ctranslate2_cuda_info() -> dict:
    """Return CTranslate2 import status and supported CUDA compute types."""
    try:
        import ctranslate2

        info = {
            "installed": True,
            "version": getattr(ctranslate2, "__version__", None),
        }
        try:
            supported = ctranslate2.get_supported_compute_types("cuda")
            info["cuda_supported_compute_types"] = sorted(supported)
            info["cuda_supported"] = bool(supported)
        except Exception as exc:  # noqa: BLE001 - diagnostic path should not hide details.
            info["cuda_supported_compute_types"] = []
            info["cuda_supported"] = False
            info["cuda_error"] = f"{type(exc).__name__}: {exc}"
        return info
    except Exception as exc:  # noqa: BLE001 - import diagnostics should capture all failures.
        return {
            "installed": False,
            "cuda_supported": False,
            "cuda_supported_compute_types": [],
            "import_error": f"{type(exc).__name__}: {exc}",
        }


def windows_path_hints() -> dict:
    """Return Windows PATH entries likely to affect CUDA DLL resolution."""
    if platform.system() != "Windows":
        return {}
    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    keywords = ("cuda", "cudnn", "nvidia", "ctranslate", "torch")
    matching = [entry for entry in entries if any(k in entry.lower() for k in keywords)]
    return {
        "python_executable": sys.executable,
        "path_entries_with_cuda_keywords": matching[:30],
        "hint": (
            "On Windows, native CUDA crashes often come from CUDA, cuDNN, or cuBLAS DLLs "
            "being missing, shadowed, or incompatible with the installed CTranslate2 wheel."
        ),
    }


def collect_cuda_diagnostics(
    device: str,
    compute_type: str,
    model_name: str,
    operation: str,
) -> dict:
    """Collect actionable CUDA runtime diagnostics."""
    return {
        "operation": operation,
        "selected_device": device,
        "selected_compute_type": compute_type,
        "model": model_name,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.replace("\n", " "),
            "python_executable": sys.executable,
        },
        "packages": package_versions(),
        "ctranslate2": ctranslate2_cuda_info(),
        "nvidia_smi": query_nvidia_smi(),
        "windows_dll_path_hints": windows_path_hints(),
    }


def format_cuda_failure_report(
    *,
    operation: str,
    failure_class: str,
    returncode: int | None,
    stdout: str,
    stderr: str,
    diagnostics: dict,
) -> str:
    """Build a readable CUDA failure report for stderr."""
    lines = [
        "CUDA inference failed.",
        f"  operation: {operation}",
        f"  failure_class: {failure_class}",
        f"  child_exit_code: {format_exit_code(returncode)}",
        f"  selected_device: {diagnostics.get('selected_device')}",
        f"  selected_compute_type: {diagnostics.get('selected_compute_type')}",
        f"  model: {diagnostics.get('model')}",
    ]

    packages = diagnostics.get("packages", {})
    if packages:
        lines.append("  packages:")
        for name, version in packages.items():
            lines.append(f"    {name}: {version or 'not installed'}")

    ct2 = diagnostics.get("ctranslate2", {})
    lines.append(
        f"  ctranslate2_cuda_supported_compute_types: {ct2.get('cuda_supported_compute_types', [])}"
    )

    smi = diagnostics.get("nvidia_smi", {})
    if smi.get("gpu_name"):
        lines.append(
            "  nvidia_smi: "
            f"{smi.get('gpu_name')} driver={smi.get('driver_version')} "
            f"cuda={smi.get('cuda_version', 'unknown')}"
        )
    elif smi.get("available"):
        lines.append(f"  nvidia_smi: available at {smi.get('path')}, query incomplete")
    else:
        lines.append("  nvidia_smi: not found")

    hints = diagnostics.get("windows_dll_path_hints", {})
    if hints:
        lines.append(f"  dll_hint: {hints.get('hint')}")
        path_entries = hints.get("path_entries_with_cuda_keywords") or []
        if path_entries:
            lines.append("  PATH entries with CUDA/NVIDIA keywords:")
            for entry in path_entries[:10]:
                lines.append(f"    {entry}")
        else:
            lines.append("  PATH entries with CUDA/NVIDIA keywords: none found")

    out_tail = tail_text(stdout)
    err_tail = tail_text(stderr)
    if out_tail:
        lines.extend(["  child_stdout_tail:", indent_block(out_tail, "    ")])
    if err_tail:
        lines.extend(["  child_stderr_tail:", indent_block(err_tail, "    ")])

    return "\n".join(lines)


def indent_block(text: str, prefix: str) -> str:
    """Indent each line in a block."""
    return "\n".join(prefix + line for line in text.splitlines())
