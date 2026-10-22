#!/usr/bin/env python3
"""Extract a single frame from a video at a given timestamp."""

import argparse
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from diagnostics import validate_source


def normalize_timestamp(ts: str) -> str:
    """Normalize a finite, nonnegative time without losing fractional seconds."""
    try:
        if ":" in ts:
            match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)", ts)
            if not match:
                raise ValueError("Use HH:MM:SS, MM:SS, or seconds")
            h, m, seconds = match.groups()
            if int(m) >= 60 or Decimal(seconds) >= 60:
                raise ValueError("Minutes and seconds must be below 60")
            total = Decimal(h or 0) * 3600 + Decimal(m) * 60 + Decimal(seconds)
        else:
            total = Decimal(ts)
        if not total.is_finite() or total < 0:
            raise ValueError("Timestamp must be finite and nonnegative")
        h = int(total // 3600)
        m = int(total % 3600 // 60)
        seconds = format(total % 60, "f")
        if "." in seconds:
            seconds = seconds.rstrip("0").rstrip(".")
        seconds = seconds.zfill(2 if "." not in seconds else len(seconds.split(".")[1]) + 3)
        return f"{h:02d}:{m:02d}:{seconds}"
    except InvalidOperation as exc:
        raise ValueError("Invalid timestamp") from exc


def timestamp_to_filename(ts: str) -> str:
    """Convert HH:MM:SS to frame_00h03m22s format."""
    parts = normalize_timestamp(ts).split(":")
    return f"frame_{parts[0]}h{parts[1]}m{parts[2]}s.png"


def main():
    parser = argparse.ArgumentParser(description="Extract a single frame from video")
    parser.add_argument("--input", required=True, help="Path to input video file")
    parser.add_argument("--output-dir", required=True, help="Output directory for frames")
    parser.add_argument(
        "--timestamp", required=True, help="Timestamp (HH:MM:SS, MM:SS, or seconds)"
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        validate_source(input_path, output_dir)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Frame extraction failed: {exc}\n")

    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    try:
        ts = normalize_timestamp(args.timestamp)
    except ValueError as exc:
        parser.error(str(exc))
    filename = timestamp_to_filename(ts)
    output_path = frames_dir / filename

    if output_path.is_file() and output_path.stat().st_size > 0:
        print(f"Frame already exists: {output_path}")
        sys.exit(0)

    result = subprocess.run(
        [
            "ffmpeg",
            "-ss",
            ts,
            "-i",
            str(input_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ffmpeg failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        parser.exit(1, "No frame produced; timestamp may be beyond the end of the video.\n")
    print(f"Frame extracted: {output_path}")


if __name__ == "__main__":
    main()
