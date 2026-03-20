#!/usr/bin/env python3
"""Get video duration using ffprobe.

Designed to run inside the video2pr conda env where ffprobe is available.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Get video duration via ffprobe")
    parser.add_argument("--input", required=True, help="Path to input video file")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(input_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ffprobe failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)
    try:
        duration = float(data["format"]["duration"])
    except (KeyError, ValueError) as e:
        print(f"Could not parse duration from ffprobe output: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Duration: {duration:.0f}s ({duration / 60:.1f} min)")


if __name__ == "__main__":
    main()
