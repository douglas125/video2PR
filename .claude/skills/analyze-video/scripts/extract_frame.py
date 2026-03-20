#!/usr/bin/env python3
"""Extract a single frame from a video at a given timestamp."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def normalize_timestamp(ts: str) -> str:
    """Normalize timestamp to HH:MM:SS format."""
    # Already HH:MM:SS
    if re.match(r"^\d{2}:\d{2}:\d{2}$", ts):
        return ts
    # MM:SS -> 00:MM:SS
    if re.match(r"^\d{1,2}:\d{2}$", ts):
        return f"00:{ts.zfill(5)}"
    # Seconds as float/int -> HH:MM:SS
    try:
        total = float(ts)
        h = int(total // 3600)
        m = int((total % 3600) // 60)
        s = int(total % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    except ValueError:
        return ts


def timestamp_to_filename(ts: str) -> str:
    """Convert HH:MM:SS to frame_00h03m22s format."""
    parts = ts.split(":")
    return f"frame_{parts[0]}h{parts[1]}m{parts[2]}s.png"


def main():
    parser = argparse.ArgumentParser(description="Extract a single frame from video")
    parser.add_argument("--input", required=True, help="Path to input video file")
    parser.add_argument("--output-dir", required=True, help="Output directory for frames")
    parser.add_argument("--timestamp", required=True, help="Timestamp (HH:MM:SS, MM:SS, or seconds)")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    ts = normalize_timestamp(args.timestamp)
    filename = timestamp_to_filename(ts)
    output_path = frames_dir / filename

    if output_path.exists():
        print(f"Frame already exists: {output_path}")
        sys.exit(0)

    result = subprocess.run(
        [
            "ffmpeg",
            "-ss", ts,
            "-i", str(input_path),
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ffmpeg failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Frame extracted: {output_path}")


if __name__ == "__main__":
    main()
