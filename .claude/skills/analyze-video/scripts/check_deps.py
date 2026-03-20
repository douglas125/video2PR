#!/usr/bin/env python3
"""Pre-flight dependency check for video2pr pipeline.

Checks that the video2pr conda environment exists and that all required
CLI tools and Python packages are available *inside* that environment.
This script itself runs from system Python — no conda activation needed.
"""

import json
import subprocess
import sys
from pathlib import Path


ENV_NAME = "video2pr"
CLI_TOOLS = ["ffmpeg", "ffprobe", "whisper"]
PYTHON_IMPORTS = {"python-docx": "docx"}


def conda_available():
    """Check if conda is on the system PATH and working."""
    try:
        result = subprocess.run(
            ["conda", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def env_exists(env_name):
    """Check if a conda environment exists."""
    result = subprocess.run(
        ["conda", "env", "list", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    envs = json.loads(result.stdout).get("envs", [])
    return any(Path(e).name == env_name for e in envs)


def check_deps_in_env():
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
        ["conda", "run", "-n", ENV_NAME, "python", "-c", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback: report everything as missing
        all_names = CLI_TOOLS + list(PYTHON_IMPORTS.keys())
        return {name: False for name in all_names}

    return json.loads(result.stdout)


def main():
    print("=== video2pr dependency check ===")

    if not conda_available():
        print("  conda: MISSING")
        print("\nMISSING: conda")
        print("\nInstall conda/miniconda first, then run:")
        print("  conda env create -f environment.yml")
        sys.exit(1)
    print("  conda: OK")

    if not env_exists(ENV_NAME):
        print(f"  conda env ({ENV_NAME}): MISSING")
        print(f"\nMISSING: conda env ({ENV_NAME})")
        print("\nTo set up the environment:")
        print("  conda env create -f environment.yml")
        sys.exit(1)
    print(f"  conda env ({ENV_NAME}): OK")

    results = check_deps_in_env()
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


if __name__ == "__main__":
    main()
