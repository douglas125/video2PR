#!/usr/bin/env python3
"""Transcribe audio using faster-whisper with built-in VAD and word timestamps."""

import argparse
import json
import re
import sys
import time
from pathlib import Path


def format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}m {s:.1f}s"


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    ms_total = round(seconds * 1000)
    h = ms_total // 3_600_000
    ms_total %= 3_600_000
    m = ms_total // 60_000
    ms_total %= 60_000
    s = ms_total // 1000
    ms = ms_total % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_timestamp(ts: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    match = re.match(r"(\d+):(\d+):(\d+),(\d+)", ts)
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def resolve_device(device: str) -> tuple[str, str]:
    """Resolve device and compute_type for faster-whisper.

    Args:
        device: "auto", "cuda", or "cpu"

    Returns:
        (device, compute_type) tuple
    """
    if device == "auto":
        # faster-whisper's "auto" handles CUDA detection;
        # for Apple Silicon MPS, CTranslate2 doesn't support it — falls back to CPU
        return "auto", "default"
    elif device == "cuda":
        return "cuda", "float16"
    else:
        return "cpu", "int8"


def load_model(model_name: str, device: str = "auto", compute_type: str = "default"):
    """Load a faster-whisper model."""
    from faster_whisper import WhisperModel

    resolved_device, resolved_compute = resolve_device(device)
    if compute_type != "default":
        resolved_compute = compute_type

    print(f"Loading Whisper model '{model_name}' (device={resolved_device}, compute={resolved_compute})...")
    return WhisperModel(model_name, device=resolved_device, compute_type=resolved_compute)


def detect_language(audio_path: Path, model_name: str = "base", device: str = "auto") -> dict:
    """Detect language from audio using faster-whisper."""
    model = load_model(model_name, device=device)

    # Use faster-whisper's built-in language detection
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=1,
        vad_filter=True,
    )
    # Must consume at least one segment to finalize detection
    for _ in segments:
        break

    alternatives = []
    if info.all_language_probs:
        for lang, prob in info.all_language_probs[:6]:
            if lang != info.language:
                alternatives.append({"language": lang, "confidence": prob})
            if len(alternatives) >= 5:
                break

    return {
        "language": info.language,
        "confidence": info.language_probability,
        "alternatives": alternatives,
    }


def write_transcript_json(path: Path, segments: list[dict]) -> None:
    """Write segments to canonical transcript JSON format."""
    transcript = {"segments": segments}
    path.write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_transcript_srt(path: Path, segments: list[dict]) -> None:
    """Write segments to SRT subtitle format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start_ts = format_srt_timestamp(seg["start"])
        end_ts = format_srt_timestamp(seg["end"])
        lines.append(str(i))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(seg["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_transcription(
    audio_path: Path,
    output_dir: Path,
    model,
    language: str | None = None,
    vad_filter: bool = True,
) -> dict:
    """Run transcription on an audio file using faster-whisper.

    Returns:
        Dict with 'segments' list and 'language' string.
    """
    segments_gen, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=vad_filter,
        language=language,
    )

    # Materialize segments from generator (transcription happens during iteration)
    segments = []
    for seg in segments_gen:
        words = []
        for w in (seg.words or []):
            word_entry = {"word": w.word, "start": w.start, "end": w.end}
            if w.probability is not None:
                word_entry["probability"] = w.probability
            words.append(word_entry)

        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": words,
        })

    # Write output files
    write_transcript_json(output_dir / "transcript.json", segments)
    write_transcript_srt(output_dir / "transcript.srt", segments)

    return {"segments": segments, "language": info.language}


def transcribe(
    audio_path: Path,
    output_dir: Path,
    model_name: str,
    device: str = "auto",
    compute_type: str = "default",
    language: str | None = None,
    vad_filter: bool = True,
) -> None:
    """Full transcription pipeline: load model, transcribe, write output."""
    model = load_model(model_name, device=device, compute_type=compute_type)

    # Get duration for speed reporting
    duration = _get_audio_duration(audio_path)
    if duration:
        print(f"Audio duration: {duration:.1f}s ({duration / 60:.1f} min)")

    start_time = time.time()
    result = run_transcription(audio_path, output_dir, model, language=language, vad_filter=vad_filter)
    elapsed = time.time() - start_time

    n_segments = len(result["segments"])
    if duration and elapsed > 0:
        ratio = duration / elapsed
        print(f"Transcription: {n_segments} segments in {format_elapsed(elapsed)} ({ratio:.1f}x realtime)")
    else:
        print(f"Transcription: {n_segments} segments in {format_elapsed(elapsed)}")


def _get_audio_duration(audio_path: Path) -> float | None:
    """Get audio duration in seconds using ffprobe. Returns None on failure."""
    import subprocess
    try:
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
            return None
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (KeyError, json.JSONDecodeError, FileNotFoundError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio using faster-whisper")
    parser.add_argument("--input", required=True, help="Path to input audio file")
    parser.add_argument("--output-dir", help="Output directory (required unless --detect-language)")
    parser.add_argument(
        "--model",
        default="small",
        choices=["base", "small", "medium", "large-v3", "turbo"],
        help="Whisper model size (default: small)",
    )
    parser.add_argument(
        "--language",
        help="Language code (e.g. en, es, pt), skipping auto-detection",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Device for inference (default: auto — tries CUDA then CPU)",
    )
    parser.add_argument(
        "--compute-type",
        default="default",
        choices=["default", "float32", "float16", "int8", "int8_float16"],
        help="Compute type for inference (default: auto-selected per device)",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Disable VAD filtering (may include silence segments)",
    )
    parser.add_argument(
        "--detect-language",
        action="store_true",
        help="Detect language from audio and output JSON to stdout",
    )
    args = parser.parse_args()

    audio_path = Path(args.input).resolve()

    if not audio_path.exists():
        print(f"Input file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    # Language detection mode
    if args.detect_language:
        result = detect_language(audio_path, model_name="base", device=args.device)
        print(json.dumps(result, indent=2))
        return

    if not args.output_dir:
        print("--output-dir is required for transcription", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    transcribe(
        audio_path,
        output_dir,
        model_name=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        vad_filter=not args.no_vad,
    )

    print("Transcription complete.")


if __name__ == "__main__":
    main()
