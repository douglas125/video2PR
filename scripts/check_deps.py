#!/usr/bin/env python3
"""Pre-flight dependency check for video2pr pipeline.

Checks that the video2pr conda environment exists and that all required
CLI tools and Python packages are available *inside* that environment.
This script itself runs from system Python — no conda activation needed.
"""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ENV_NAME = "video2pr"
CLI_TOOLS = ["ffmpeg", "ffprobe", "whisper"]
PYTHON_IMPORTS = {"python-docx": "docx"}


def parse_json_output(output: str):
    """Extract a JSON value from mixed stdout/stderr style output.

    Some `conda run` invocations on Windows emit extra banner or status lines
    before/after the actual JSON payload. Prefer whole-line JSON first, then
    fall back to scanning for the first decodable object/array in the text.
    """
    decoder = json.JSONDecoder()

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value, end = decoder.raw_decode(line)
        except json.JSONDecodeError:
            continue
        if line[end:].strip():
            continue
        return value

    for idx, char in enumerate(output):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(output[idx:])
        except json.JSONDecodeError:
            continue
        return value

    return None


def find_conda():
    """Find the conda executable path, with Windows fallback.

    Tries shutil.which first. On Windows, checks common install locations
    if conda is not on PATH (e.g. Git Bash sessions).

    Returns the path string or None.
    """
    exe = shutil.which("conda")
    if exe is not None:
        return exe

    if platform.system() != "Windows":
        return None

    # Common Windows conda install locations
    home = Path.home()
    candidates = [
        home / "miniconda3" / "condabin" / "conda.bat",
        home / "anaconda3" / "condabin" / "conda.bat",
        home / "Miniconda3" / "condabin" / "conda.bat",
        home / "Anaconda3" / "condabin" / "conda.bat",
        Path(r"C:\ProgramData\miniconda3\condabin\conda.bat"),
        Path(r"C:\ProgramData\anaconda3\condabin\conda.bat"),
        Path(r"C:\ProgramData\Miniconda3\condabin\conda.bat"),
        Path(r"C:\ProgramData\Anaconda3\condabin\conda.bat"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def conda_available():
    """Check if conda is findable and working."""
    conda_path = find_conda()
    if conda_path is None:
        return False
    try:
        result = subprocess.run(
            [conda_path, "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def env_exists(env_name, conda_path="conda"):
    """Check if a conda environment exists."""
    result = subprocess.run(
        [conda_path, "env", "list", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    payload = parse_json_output(result.stdout)
    if not isinstance(payload, dict):
        return False
    envs = payload.get("envs", [])
    return any(Path(e).name == env_name for e in envs)


def check_deps_in_env(conda_path="conda"):
    """Check all CLI tools and Python imports in a single conda run call.

    Returns (cli_results, import_results) where each is a dict of name -> bool.
    """
    # Build a single Python script that checks everything
    checks = []
    for tool in CLI_TOOLS:
        checks.append(f"import shutil; results[{tool!r}] = shutil.which({tool!r}) is not None")
    for name, module in PYTHON_IMPORTS.items():
        checks.append(
            f"try:\n    __import__({module!r}); results[{name!r}] = True\n"
            f"except ImportError:\n    results[{name!r}] = False"
        )

    script = "import shutil, json\nresults = {}\n" + "\n".join(checks) + "\nprint(json.dumps(results))"

    result = subprocess.run(
        [conda_path, "run", "-n", ENV_NAME, "python", "-c", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback: report everything as missing
        all_names = CLI_TOOLS + list(PYTHON_IMPORTS.keys())
        return {name: False for name in all_names}
    payload = parse_json_output(result.stdout)
    if isinstance(payload, dict):
        return payload

    all_names = CLI_TOOLS + list(PYTHON_IMPORTS.keys())
    return {name: False for name in all_names}


def main():
    print("=== video2pr dependency check ===")

    conda_path = find_conda()
    if conda_path is None:
        print("  conda: MISSING")
        print("\nMISSING: conda")
        print("\nInstall conda/miniconda first, then run:")
        print("  conda env create -f environment.yml")
        sys.exit(1)
    print("  conda: OK")
    print(f"CONDA_PATH: {conda_path}")

    if not env_exists(ENV_NAME, conda_path):
        print(f"  conda env ({ENV_NAME}): MISSING")
        print(f"\nMISSING: conda env ({ENV_NAME})")
        print("\nTo set up the environment:")
        print("  conda env create -f environment.yml")
        sys.exit(1)
    print(f"  conda env ({ENV_NAME}): OK")

    results = check_deps_in_env(conda_path)
    missing = []
    for name, found in results.items():
        status = "OK" if found else "MISSING"
        print(f"  {name}: {status}")
        if not found:
            missing.append(name)

    if missing:
        print(f"\nMISSING: {', '.join(missing)}")
        print("\nTo fix, update the environment:")
        print("  conda env update -f environment.yml")
        sys.exit(1)

    print("\nAll dependencies found.")

    # GPU status check
    gpu_script = Path(__file__).resolve().parent / "check_gpu.py"
    if gpu_script.exists():
        gpu_result = subprocess.run(
            [conda_path, "run", "-n", ENV_NAME, "python", str(gpu_script)],
            capture_output=True,
            text=True,
        )
        if gpu_result.returncode == 0:
            gpu_info = parse_json_output(gpu_result.stdout)
            try:
                if not isinstance(gpu_info, dict):
                    raise ValueError("missing JSON payload")
                device = gpu_info.get("device", "cpu")
                gpu_name = gpu_info.get("gpu_name")
                cuda_version = gpu_info.get("cuda_version")
                available = gpu_info.get("torch_device_available", False)
                install_cmd = gpu_info.get("install_command")

                if device == "cuda" and available:
                    print(f"  GPU: {gpu_name} (CUDA {cuda_version}) — OK")
                elif device == "mps" and available:
                    print("  GPU: Apple Silicon (MPS) — OK")
                elif gpu_name and not available:
                    print(f"  GPU: {gpu_name} detected, PyTorch is CPU-only")
                    if install_cmd:
                        print(f"  To enable GPU acceleration (~5-20x faster transcription):")
                        print(f"    {install_cmd}")
                else:
                    print("  GPU: CPU only")
            except (ValueError, KeyError):
                print("  GPU: detection failed")


if __name__ == "__main__":
    main()
