#!/usr/bin/env python3
"""Transcribe audio using OpenAI Whisper with chunking for long files."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ffprobe failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def split_audio(audio_path: Path, chunk_duration: int, temp_dir: Path) -> list[Path]:
    """Split audio into chunks of chunk_duration seconds."""
    duration = get_audio_duration(audio_path)
    chunks = []
    start = 0
    idx = 0

    while start < duration:
        chunk_path = temp_dir / f"chunk_{idx:04d}.wav"
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", str(audio_path),
                "-ss", str(start),
                "-t", str(chunk_duration),
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-y",
                str(chunk_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ffmpeg chunk split failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        chunks.append(chunk_path)
        start += chunk_duration
        idx += 1

    return chunks


def run_whisper(audio_path: Path, output_dir: Path, model: str) -> None:
    """Run whisper on an audio file."""
    result = subprocess.run(
        [
            "whisper",
            str(audio_path),
            "--model", model,
            "--word_timestamps", "True",
            "--output_format", "all",
            "--output_dir", str(output_dir),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Whisper failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)


def parse_srt_timestamp(ts: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    match = re.match(r"(\d+):(\d+):(\d+),(\d+)", ts)
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def offset_srt(srt_text: str, offset_seconds: float, start_index: int) -> tuple[str, int]:
    """Offset all timestamps in an SRT string and renumber entries."""
    lines = srt_text.strip().split("\n")
    result_lines = []
    current_index = start_index
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Skip the original sequence number
        if line.isdigit():
            i += 1
            if i >= len(lines):
                break
            line = lines[i].strip()

        # Check for timestamp line
        ts_match = re.match(
            r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", line
        )
        if ts_match:
            start = parse_srt_timestamp(ts_match.group(1)) + offset_seconds
            end = parse_srt_timestamp(ts_match.group(2)) + offset_seconds
            result_lines.append(str(current_index))
            result_lines.append(
                f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}"
            )
            current_index += 1
            i += 1
            # Collect subtitle text lines
            while i < len(lines) and lines[i].strip():
                result_lines.append(lines[i].strip())
                i += 1
            result_lines.append("")
        else:
            i += 1

    return "\n".join(result_lines), current_index


def offset_json_segments(segments: list[dict], offset_seconds: float) -> list[dict]:
    """Offset timestamps in whisper JSON segments."""
    result = []
    for seg in segments:
        new_seg = dict(seg)
        new_seg["start"] = seg["start"] + offset_seconds
        new_seg["end"] = seg["end"] + offset_seconds
        if "words" in seg:
            new_seg["words"] = []
            for w in seg["words"]:
                new_w = dict(w)
                new_w["start"] = w["start"] + offset_seconds
                new_w["end"] = w["end"] + offset_seconds
                new_seg["words"].append(new_w)
        result.append(new_seg)
    return result


def transcribe_single(audio_path: Path, output_dir: Path, model: str) -> None:
    """Transcribe a single audio file directly."""
    run_whisper(audio_path, output_dir, model)

    # Whisper outputs files named after the input audio stem
    stem = audio_path.stem
    whisper_json = output_dir / f"{stem}.json"
    whisper_srt = output_dir / f"{stem}.srt"

    # Rename to canonical names
    if whisper_json.exists() and stem != "transcript":
        target_json = output_dir / "transcript.json"
        whisper_json.rename(target_json)
    if whisper_srt.exists() and stem != "transcript":
        target_srt = output_dir / "transcript.srt"
        whisper_srt.rename(target_srt)


def transcribe_chunked(
    audio_path: Path, output_dir: Path, model: str, chunk_duration: int = 1800
) -> None:
    """Transcribe long audio by splitting into chunks and merging."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        chunks = split_audio(audio_path, chunk_duration, tmp_dir)
        print(f"Split into {len(chunks)} chunks of {chunk_duration}s each")

        all_srt = ""
        all_segments: list[dict] = []
        srt_index = 1

        for i, chunk_path in enumerate(chunks):
            offset = i * chunk_duration
            print(f"Transcribing chunk {i + 1}/{len(chunks)}...")

            chunk_out = tmp_dir / f"chunk_{i:04d}_out"
            chunk_out.mkdir(exist_ok=True)
            run_whisper(chunk_path, chunk_out, model)

            # Read chunk SRT
            chunk_srt_path = chunk_out / f"{chunk_path.stem}.srt"
            if chunk_srt_path.exists():
                chunk_srt = chunk_srt_path.read_text()
                offset_text, srt_index = offset_srt(chunk_srt, offset, srt_index)
                all_srt += offset_text + "\n"

            # Read chunk JSON
            chunk_json_path = chunk_out / f"{chunk_path.stem}.json"
            if chunk_json_path.exists():
                chunk_data = json.loads(chunk_json_path.read_text())
                segments = chunk_data.get("segments", [])
                all_segments.extend(offset_json_segments(segments, offset))

        # Write merged outputs
        srt_path = output_dir / "transcript.srt"
        srt_path.write_text(all_srt.strip() + "\n")
        print(f"Merged SRT saved to {srt_path}")

        json_path = output_dir / "transcript.json"
        merged = {"segments": all_segments}
        json_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
        print(f"Merged JSON saved to {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio using Whisper")
    parser.add_argument("--input", required=True, help="Path to input audio file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--model",
        default="base",
        choices=["base", "medium", "large"],
        help="Whisper model size (default: base)",
    )
    args = parser.parse_args()

    audio_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not audio_path.exists():
        print(f"Input file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    duration = get_audio_duration(audio_path)
    print(f"Audio duration: {duration:.1f}s ({duration / 60:.1f} min)")

    # Use chunking for files over 30 minutes
    if duration > 1800:
        transcribe_chunked(audio_path, output_dir, args.model)
    else:
        transcribe_single(audio_path, output_dir, args.model)

    print("Transcription complete.")


if __name__ == "__main__":
    main()
