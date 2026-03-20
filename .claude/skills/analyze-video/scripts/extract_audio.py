#!/usr/bin/env python3
"""Extract audio from video and save ffprobe metadata."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_metadata(input_path: Path) -> dict:
    """Extract video metadata using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(input_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ffprobe failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def extract_audio(input_path: Path, output_dir: Path) -> Path:
    """Extract audio as 16kHz mono WAV."""
    output_path = output_dir / "audio.wav"
    result = subprocess.run(
        [
            "ffmpeg",
            "-i", str(input_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ffmpeg failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Extract audio from video file")
    parser.add_argument("--input", required=True, help="Path to input video file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Save metadata
    print(f"Extracting metadata from {input_path.name}...")
    metadata = get_metadata(input_path)
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    print(f"Metadata saved to {metadata_path}")

    # Extract audio
    print(f"Extracting audio from {input_path.name}...")
    audio_path = extract_audio(input_path, output_dir)
    print(f"Audio saved to {audio_path}")


if __name__ == "__main__":
    main()
