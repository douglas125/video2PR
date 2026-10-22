#!/usr/bin/env python3
"""Pre-flight dependency check for video2pr pipeline.

Checks that the video2pr conda environment exists and that all required
CLI tools and Python packages are available *inside* that environment.
This script itself runs from system Python — no conda activation needed.
"""

import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENV_NAME = "video2pr"
CLI_TOOLS = ["ffmpeg", "ffprobe"]
PYTHON_IMPORTS = {"faster-whisper": "faster_whisper", "python-docx": "docx"}


def parse_json_output(output: str):
    """Extract a JSON value from mixed stdout/stderr style output.

    Some `conda run` invocations on Windows emit extra banner or status lines
    before/after the actual JSON payload. Prefer whole-line JSON first, then
    fall back to scanning for the first decodable object/array in the text.
    """
    decoder = json.JSONDecoder()

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

    Returns a validated dictionary of every required dependency name to bool.
    """
    # Build a single Python script that checks everything
    checks = []
    for tool in CLI_TOOLS:
        checks.append(f"import shutil; results[{tool!r}] = shutil.which({tool!r}) is not None")
    for name, module in PYTHON_IMPORTS.items():
        checks.append(
            f"try:\n    __import__({module!r}); results[{name!r}] = True\n"
            f"except Exception:\n    results[{name!r}] = False"
        )

    script = (
        "import shutil, json\nresults = {}\n" + "\n".join(checks) + "\nprint(json.dumps(results))"
    )

    # Write the script to a temp .py file rather than passing it via `python -c`.
    # On Windows, conda is a .bat wrapper invoked through cmd.exe, which mangles
    # arguments containing newlines — a multi-line `-c` script silently produces
    # empty stdout in that path, making every dep look missing.
    fd, tmp_path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(script)
        result = subprocess.run(
            [conda_path, "run", "-n", ENV_NAME, "python", tmp_path],
            capture_output=True,
            text=True,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
    if result.returncode != 0:
        print(f"Dependency probe failed: {result.stderr.strip()}", file=sys.stderr)
        # Fallback: report everything as missing
        all_names = CLI_TOOLS + list(PYTHON_IMPORTS.keys())
        return dict.fromkeys(all_names, False)
    payload = parse_json_output(result.stdout)
    if isinstance(payload, dict):
        return {name: payload.get(name) is True for name in CLI_TOOLS + list(PYTHON_IMPORTS)}

    all_names = CLI_TOOLS + list(PYTHON_IMPORTS.keys())
    return dict.fromkeys(all_names, False)


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
    for name in CLI_TOOLS + list(PYTHON_IMPORTS):
        found = results.get(name) is True
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


if __name__ == "__main__":
    main()
