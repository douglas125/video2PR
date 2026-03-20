#!/usr/bin/env python3
"""Pre-flight dependency check for video2pr pipeline."""

import shutil
import subprocess
import sys


def check_command(name):
    """Check if a command is available on PATH."""
    return shutil.which(name) is not None


def check_conda_env(env_name):
    """Check if a conda environment exists."""
    try:
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            import json

            envs = json.loads(result.stdout).get("envs", [])
            return any(e.endswith(f"/{env_name}") for e in envs)
    except FileNotFoundError:
        pass
    return False


def check_python_import(module_name):
    """Check if a Python module can be imported."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def main():
    deps = {
        "ffmpeg": check_command("ffmpeg"),
        "ffprobe": check_command("ffprobe"),
        "whisper": check_command("whisper"),
    }
    pip_deps = {
        "python-docx": check_python_import("docx"),
    }
    conda_ok = check_conda_env("video2pr")

    print("=== video2pr dependency check ===")
    for name, found in deps.items():
        status = "OK" if found else "MISSING"
        print(f"  {name}: {status}")
    for name, found in pip_deps.items():
        status = "OK" if found else "MISSING"
        print(f"  {name}: {status}")

    print(f"  conda env (video2pr): {'OK' if conda_ok else 'MISSING'}")

    missing = [name for name, found in deps.items() if not found]
    missing.extend(name for name, found in pip_deps.items() if not found)
    if not conda_ok:
        missing.append("conda env (video2pr)")

    if missing:
        print(f"\nMISSING: {', '.join(missing)}")
        print("\nTo set up the environment:")
        print("  conda env create -f environment.yml")
        print("  conda activate video2pr")
    else:
        print("\nAll dependencies found.")

    sys.exit(0)


if __name__ == "__main__":
    main()
