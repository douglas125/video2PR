#!/usr/bin/env python3
"""Parse external transcripts (Google Meet, MS Teams, Zoom) into canonical JSON format."""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def detect_format(input_path: Path) -> str:
    """Auto-detect transcript format from extension and content patterns."""
    ext = input_path.suffix.lower()

    if ext == ".docx":
        return "teams_docx"
    if ext == ".sbv":
        return "sbv"

    content = input_path.read_text(encoding="utf-8", errors="replace")

    if ext == ".vtt" or content.strip().startswith("WEBVTT"):
        # Teams VTT has <v Speaker> tags
        if re.search(r"<v\s+[^>]+>", content):
            return "teams_vtt"
        # Zoom VTT has "Speaker Name: text" inline (after timestamp lines)
        # Look for pattern after a timestamp arrow line
        if re.search(
            r"-->\s*[\d:.]+.*\n[A-Z][\w\s]+:\s+\S",
            content,
        ):
            return "zoom_vtt"
        # Generic VTT fallback (no speaker detection)
        return "zoom_vtt"  # default VTT to zoom parser (handles both with/without speakers)

    # Google Meet .txt: lines like "Speaker Name (0:12:34)"
    if re.search(r"^.+ \(\d+:\d+:\d+\)$", content, re.MULTILINE):
        return "google_txt"

    # Zoom TXT: "Speaker Name   HH:MM:SS" with 2+ spaces, text on next line
    if re.search(r"^.+\s{2,}\d{2}:\d{2}:\d{2}\s*$", content, re.MULTILINE):
        return "zoom_txt"

    # SBV pattern: "0:00:01.234,0:00:05.678"
    if re.search(r"^\d+:\d+:\d+\.\d+,", content, re.MULTILINE):
        return "sbv"

    print(f"Could not detect transcript format for {input_path}", file=sys.stderr)
    sys.exit(1)


def parse_sbv_timestamp(ts: str) -> float:
    """Parse SBV timestamp (H:MM:SS.mmm) to seconds."""
    match = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", ts.strip())
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_sbv(content: str) -> list[dict]:
    """Parse Google Meet SBV format."""
    segments = []
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # First line: timestamp range
        ts_match = re.match(
            r"(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+)", lines[0]
        )
        if not ts_match:
            continue

        start = parse_sbv_timestamp(ts_match.group(1))
        end = parse_sbv_timestamp(ts_match.group(2))
        text = "\n".join(lines[1:]).strip()

        # Check for speaker prefix like "Speaker Name: text"
        speaker = None
        speaker_match = re.match(r"^([^:]+):\s*(.+)$", text, re.DOTALL)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            text = speaker_match.group(2).strip()

        segments.append({
            "start": start,
            "end": end,
            "text": text,
            "speaker": speaker,
            "words": [],
        })

    return segments


def parse_vtt_timestamp(ts: str) -> float:
    """Parse VTT timestamp (HH:MM:SS.mmm) to seconds."""
    match = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", ts.strip())
    if not match:
        # Try MM:SS.mmm format
        match = re.match(r"(\d+):(\d+)\.(\d+)", ts.strip())
        if match:
            m, s, ms = match.groups()
            return int(m) * 60 + int(s) + int(ms) / 1000
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_teams_vtt(content: str) -> list[dict]:
    """Parse MS Teams VTT format with <v Name> speaker tags."""
    segments = []
    # Remove WEBVTT header and any NOTE blocks
    content = re.sub(r"^WEBVTT.*?\n\n", "", content, flags=re.DOTALL)
    content = re.sub(r"NOTE.*?\n\n", "", content, flags=re.DOTALL)

    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        # Find timestamp line
        ts_line = None
        text_lines = []
        for line in lines:
            ts_match = re.match(
                r"(\d+:\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+)", line
            )
            if not ts_match and re.match(
                r"(\d+:\d+\.\d+)\s*-->\s*(\d+:\d+\.\d+)", line
            ):
                ts_match = re.match(
                    r"(\d+:\d+\.\d+)\s*-->\s*(\d+:\d+\.\d+)", line
                )
            if ts_match:
                ts_line = ts_match
            elif ts_line is not None:
                text_lines.append(line)

        if not ts_line or not text_lines:
            continue

        start = parse_vtt_timestamp(ts_line.group(1))
        end = parse_vtt_timestamp(ts_line.group(2))
        text = "\n".join(text_lines).strip()

        # Check for <v Name> speaker tags (MS Teams format)
        speaker = None
        v_match = re.match(r"<v\s+([^>]+)>(.*?)(?:</v>)?$", text, re.DOTALL)
        if v_match:
            speaker = v_match.group(1).strip()
            text = v_match.group(2).strip()

        segments.append({
            "start": start,
            "end": end,
            "text": text,
            "speaker": speaker,
            "words": [],
        })

    return segments


def parse_zoom_vtt(content: str) -> list[dict]:
    """Parse Zoom VTT format with inline 'Speaker Name: text' speaker attribution."""
    segments = []
    # Remove WEBVTT header and any metadata lines (Kind:, Language:)
    content = re.sub(r"^WEBVTT.*?\n\n", "", content, flags=re.DOTALL)
    content = re.sub(r"NOTE.*?\n\n", "", content, flags=re.DOTALL)

    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        # Find timestamp line
        ts_line = None
        text_lines = []
        for line in lines:
            ts_match = re.match(
                r"(\d+:\d+:\d+\.\d+)\s*-->\s*(\d+:\d+:\d+\.\d+)", line
            )
            if not ts_match and re.match(
                r"(\d+:\d+\.\d+)\s*-->\s*(\d+:\d+\.\d+)", line
            ):
                ts_match = re.match(
                    r"(\d+:\d+\.\d+)\s*-->\s*(\d+:\d+\.\d+)", line
                )
            if ts_match:
                ts_line = ts_match
            elif ts_line is not None:
                text_lines.append(line)

        if not ts_line or not text_lines:
            continue

        start = parse_vtt_timestamp(ts_line.group(1))
        end = parse_vtt_timestamp(ts_line.group(2))
        text = "\n".join(text_lines).strip()

        # Zoom VTT: "Speaker Name: text" inline format
        speaker = None
        # Match "Name: text" but avoid false positives on common patterns
        # like "Time: 3pm" or "Note: something" by requiring at least 2 words
        # or a capitalized multi-word name
        speaker_match = re.match(r"^([A-Z][\w\s.-]+?):\s+(.+)$", text, re.DOTALL)
        if speaker_match:
            candidate_speaker = speaker_match.group(1).strip()
            # Avoid single common words that look like labels, not names
            label_words = {"note", "time", "update", "action", "topic", "summary", "status"}
            if candidate_speaker.lower() not in label_words:
                speaker = candidate_speaker
                text = speaker_match.group(2).strip()

        segments.append({
            "start": start,
            "end": end,
            "text": text,
            "speaker": speaker,
            "words": [],
        })

    return segments


def parse_zoom_txt(content: str) -> list[dict]:
    """Parse Zoom TXT format with 'Speaker Name   HH:MM:SS' headers."""
    segments = []
    # Match lines like "Speaker Name   00:12:34" (2+ spaces between name and time)
    header_pattern = re.compile(r"^(.+?)\s{2,}(\d{2}:\d{2}:\d{2})\s*$", re.MULTILINE)
    headers = list(header_pattern.finditer(content))

    for i, match in enumerate(headers):
        speaker = match.group(1).strip()
        ts_str = match.group(2)
        parts = ts_str.split(":")
        start = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

        # Text is between this header and the next
        text_start = match.end()
        text_end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        text = content[text_start:text_end].strip()

        # End time = next segment's start, or start + 30s for last segment
        end = (
            int(headers[i + 1].group(2).split(":")[0]) * 3600
            + int(headers[i + 1].group(2).split(":")[1]) * 60
            + int(headers[i + 1].group(2).split(":")[2])
            if i + 1 < len(headers)
            else start + 30
        )

        if text:
            segments.append({
                "start": float(start),
                "end": float(end),
                "text": text,
                "speaker": speaker,
                "words": [],
            })

    return segments


def parse_google_txt(content: str) -> list[dict]:
    """Parse Google Meet .txt format with speaker headers like 'Name (H:MM:SS)'."""
    segments = []
    # Match lines like "Speaker Name (0:12:34)"
    header_pattern = re.compile(r"^(.+?)\s*\((\d+:\d+:\d+)\)\s*$", re.MULTILINE)
    headers = list(header_pattern.finditer(content))

    for i, match in enumerate(headers):
        speaker = match.group(1).strip()
        ts_str = match.group(2)
        parts = ts_str.split(":")
        start = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

        # Text is between this header and the next
        text_start = match.end()
        text_end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        text = content[text_start:text_end].strip()

        # End time = next segment's start, or start + 30s for last segment
        end = (
            int(headers[i + 1].group(2).split(":")[0]) * 3600
            + int(headers[i + 1].group(2).split(":")[1]) * 60
            + int(headers[i + 1].group(2).split(":")[2])
            if i + 1 < len(headers)
            else start + 30
        )

        if text:
            segments.append({
                "start": float(start),
                "end": float(end),
                "text": text,
                "speaker": speaker,
                "words": [],
            })

    return segments


def parse_teams_docx(input_path: Path) -> list[dict]:
    """Parse MS Teams .docx transcript."""
    from docx import Document

    doc = Document(str(input_path))
    segments = []
    current_speaker = None
    current_start = 0.0
    current_texts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # Teams docx typically has speaker + timestamp lines followed by text
        # Pattern: "Speaker Name  0:12:34"
        header_match = re.match(r"^(.+?)\s{2,}(\d+:\d+:\d+)\s*$", text)
        if header_match:
            # Save previous segment
            if current_texts:
                segments.append({
                    "start": current_start,
                    "end": current_start + 30,  # placeholder until next segment
                    "text": " ".join(current_texts),
                    "speaker": current_speaker,
                    "words": [],
                })

            current_speaker = header_match.group(1).strip()
            ts_parts = header_match.group(2).split(":")
            current_start = (
                float(int(ts_parts[0]) * 3600 + int(ts_parts[1]) * 60 + int(ts_parts[2]))
            )
            current_texts = []
        else:
            current_texts.append(text)

    # Save final segment
    if current_texts:
        segments.append({
            "start": current_start,
            "end": current_start + 30,
            "text": " ".join(current_texts),
            "speaker": current_speaker,
            "words": [],
        })

    # Fix end times: each segment ends when the next begins
    for i in range(len(segments) - 1):
        segments[i]["end"] = segments[i + 1]["start"]

    return segments


def convert(input_path: Path, output_dir: Path, fmt: str) -> None:
    """Convert external transcript to canonical format."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detect format if auto
    if fmt == "auto":
        fmt = detect_format(input_path)

    print(f"Detected format: {fmt}")

    # Parse based on format
    if fmt == "teams_docx":
        segments = parse_teams_docx(input_path)
    else:
        content = input_path.read_text(encoding="utf-8", errors="replace")
        parsers = {
            "sbv": parse_sbv,
            "teams_vtt": parse_teams_vtt,
            "zoom_vtt": parse_zoom_vtt,
            "zoom_txt": parse_zoom_txt,
            "google_txt": parse_google_txt,
            "vtt": parse_zoom_vtt,  # generic VTT uses zoom parser (handles both)
        }
        parser = parsers.get(fmt)
        if parser is None:
            print(f"Unknown format: {fmt}", file=sys.stderr)
            sys.exit(1)
        segments = parser(content)

    print(f"Parsed {len(segments)} segments")

    has_speakers = any(seg["speaker"] for seg in segments)
    has_timestamps = any(seg["start"] > 0 or seg["end"] > 0 for seg in segments)

    # Write canonical transcript.json
    transcript = {"segments": segments}
    transcript_path = output_dir / "transcript.json"
    transcript_path.write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Transcript saved to {transcript_path}")

    # Write metadata
    format_labels = {
        "sbv": "google_meet_sbv",
        "teams_vtt": "ms_teams_vtt",
        "vtt": "vtt_generic",
        "zoom_vtt": "zoom_vtt",
        "zoom_txt": "zoom_txt",
        "google_txt": "google_meet_txt",
        "teams_docx": "ms_teams_docx",
    }
    meta = {
        "source": format_labels.get(fmt, fmt),
        "has_timestamps": has_timestamps,
        "has_speakers": has_speakers,
        "original_file": input_path.name,
        "segment_count": len(segments),
    }
    meta_path = output_dir / "external_transcript_meta.json"
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Metadata saved to {meta_path}")

    # Copy original file
    dest_ext = input_path.suffix
    original_copy = output_dir / f"external_transcript_original{dest_ext}"
    shutil.copy2(input_path, original_copy)
    print(f"Original copied to {original_copy}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert external transcripts to canonical JSON format"
    )
    parser.add_argument("--input", required=True, help="Path to transcript file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--format",
        default="auto",
        choices=["auto", "sbv", "vtt", "teams_vtt", "zoom_vtt", "zoom_txt", "google_txt", "teams_docx"],
        help="Transcript format (default: auto-detect)",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    convert(input_path, output_dir, args.format)


if __name__ == "__main__":
    main()
