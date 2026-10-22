#!/usr/bin/env python3
"""Extract audio from video and save ffprobe metadata."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from artifacts import json_bytes, source_identity, validate_source
from check_update import replace_paths


def get_metadata(input_path: Path) -> dict:
    """Extract video metadata using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
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
            "-i",
            str(input_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
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

    try:
        validate_source(input_path, output_dir)
        print(f"Extracting metadata and audio from {input_path.name}...")
        metadata = get_metadata(input_path)
        with tempfile.TemporaryDirectory(prefix=".audio-", dir=output_dir) as tmp:
            stage = Path(tmp)
            audio_path = extract_audio(input_path, stage)
            (stage / "metadata.json").write_bytes(json_bytes(metadata))
            (stage / "source.json").write_bytes(json_bytes(source_identity(input_path)))
            replace_paths(
                [
                    (audio_path, output_dir / "audio.wav"),
                    (stage / "metadata.json", output_dir / "metadata.json"),
                    (stage / "source.json", output_dir / "source.json"),
                ]
            )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Audio extraction failed: {exc}\n")
    print(f"Audio saved to {output_dir / 'audio.wav'}")


if __name__ == "__main__":
    main()
