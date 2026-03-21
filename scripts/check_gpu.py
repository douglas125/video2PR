#!/usr/bin/env python3
"""Detect GPU hardware and PyTorch device availability.

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


def _map_cuda_to_wheel(cuda_version_str):
    """Map a CUDA version string to the PyTorch wheel suffix.

    Returns e.g. "cu124", "cu121", "cu118".
    """
    try:
        parts = cuda_version_str.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return "cu124"  # default to latest supported

    if major >= 13 or (major == 12 and minor >= 4):
        return "cu124"
    elif major == 12 and minor >= 1:
        return "cu121"
    else:
        return "cu118"


def _check_torch():
    """Check PyTorch installation and device availability.

    Returns (installed, version, cuda_available, mps_available).
    """
    try:
        import torch

        cuda_avail = torch.cuda.is_available()
        mps_avail = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        return True, torch.__version__, cuda_avail, mps_avail
    except ImportError:
        return False, None, False, False


def check_gpu():
    """Detect GPU hardware and PyTorch device status.

    Returns a dict with detection results.
    """
    plat = platform.system()
    arch = platform.machine()

    # Detect NVIDIA GPU
    gpu_name, _ = _run_nvidia_smi_query()
    cuda_version = _parse_cuda_version() if gpu_name else None

    # Detect Apple Silicon
    is_apple_silicon = plat == "Darwin" and arch == "arm64"

    # Check PyTorch
    torch_installed, torch_version, cuda_avail, mps_avail = _check_torch()

    # Determine device and availability
    if cuda_avail:
        device = "cuda"
        torch_device_available = True
    elif mps_avail:
        device = "mps"
        torch_device_available = True
    else:
        device = "cpu"
        torch_device_available = False

    # Build install command if GPU exists but torch can't use it
    install_command = None
    if gpu_name and not cuda_avail:
        # NVIDIA GPU present but torch can't use CUDA
        wheel_tag = _map_cuda_to_wheel(cuda_version) if cuda_version else "cu124"
        install_command = (
            f"pip install torch torchvision torchaudio"
            f" --index-url https://download.pytorch.org/whl/{wheel_tag}"
        )
    elif is_apple_silicon and not mps_avail:
        install_command = "pip install --upgrade torch torchvision torchaudio"

    # Build message
    if device == "cuda":
        msg = f"GPU acceleration: {gpu_name} via CUDA {cuda_version or 'unknown'}"
    elif device == "mps":
        msg = "GPU acceleration: Apple Silicon (MPS)"
    elif gpu_name:
        msg = f"GPU detected ({gpu_name}) but PyTorch is CPU-only"
    elif is_apple_silicon:
        msg = "Apple Silicon detected but MPS not available in PyTorch"
    else:
        msg = "Running on CPU (no GPU detected)"

    return {
        "platform": plat,
        "arch": arch,
        "device": device,
        "gpu_name": gpu_name,
        "cuda_version": cuda_version,
        "torch_installed": torch_installed,
        "torch_version": torch_version,
        "torch_device_available": torch_device_available,
        "install_command": install_command,
        "message": msg,
    }


def main():
    result = check_gpu()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
