#!/usr/bin/env python3
"""Transcribe audio using faster-whisper with built-in VAD and word timestamps."""

import argparse
import contextlib
import faulthandler
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diagnostics import (  # noqa: E402
    PYTHON_EXCEPTION_MARKER,
    classify_worker_failure,
    collect_cuda_diagnostics,
    format_cuda_failure_report,
)

CUDA_WORKER_ARG = "--_video2pr-worker"
CUDA_WORKER_TIMEOUT_SECONDS = 60 * 60 * 12
REQUIRED_RUNTIME_MODULES = {"faster-whisper": "faster_whisper"}


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

    print(
        f"Loading Whisper model '{model_name}' (device={resolved_device}, compute={resolved_compute})..."
    )
    return WhisperModel(model_name, device=resolved_device, compute_type=resolved_compute)


def ensure_runtime_dependencies() -> None:
    """Fail early when the script is not running in the video2pr environment."""
    missing = [
        package
        for package, module_name in REQUIRED_RUNTIME_MODULES.items()
        if importlib.util.find_spec(module_name) is None
    ]
    if not missing:
        return

    print(
        "Missing runtime dependency: "
        f"{', '.join(missing)}. Run this script inside the video2pr environment.",
        file=sys.stderr,
    )
    print(f"Current Python: {sys.executable}", file=sys.stderr)
    print("Expected usage:", file=sys.stderr)
    print("  conda run -n video2pr python scripts/transcribe.py ...", file=sys.stderr)
    sys.exit(1)


def detect_language(
    audio_path: Path,
    model_name: str = "base",
    device: str = "auto",
    compute_type: str = "default",
) -> dict:
    """Detect language from audio using faster-whisper."""
    model = load_model(model_name, device=device, compute_type=compute_type)

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
        for w in seg.words or []:
            word_entry = {"word": w.word, "start": w.start, "end": w.end}
            if w.probability is not None:
                word_entry["probability"] = w.probability
            words.append(word_entry)

        segments.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "words": words,
            }
        )

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
    result = run_transcription(
        audio_path, output_dir, model, language=language, vad_filter=vad_filter
    )
    elapsed = time.time() - start_time

    n_segments = len(result["segments"])
    if duration and elapsed > 0:
        ratio = duration / elapsed
        print(
            f"Transcription: {n_segments} segments in {format_elapsed(elapsed)} ({ratio:.1f}x realtime)"
        )
    else:
        print(f"Transcription: {n_segments} segments in {format_elapsed(elapsed)}")


def _get_audio_duration(audio_path: Path) -> float | None:
    """Get audio duration in seconds using ffprobe. Returns None on failure."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
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


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    """Configure command-line arguments."""
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
    parser.add_argument(
        CUDA_WORKER_ARG,
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _run_cli(args: argparse.Namespace) -> None:
    """Run the requested command in the current process."""
    audio_path = Path(args.input).resolve()

    if not audio_path.exists():
        print(f"Input file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    # Language detection mode
    if args.detect_language:
        result = detect_language(
            audio_path,
            model_name="base",
            device=args.device,
            compute_type=args.compute_type,
        )
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


def _operation_name(args: argparse.Namespace) -> str:
    return "language_detection" if args.detect_language else "transcription"


def _worker_command(args: argparse.Namespace, device: str) -> list[str]:
    """Build a child process command for isolated CUDA execution."""
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        CUDA_WORKER_ARG,
        "--input",
        str(Path(args.input).resolve()),
        "--device",
        device,
        "--compute-type",
        args.compute_type,
    ]
    if args.output_dir:
        cmd.extend(["--output-dir", str(Path(args.output_dir).resolve())])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.language:
        cmd.extend(["--language", args.language])
    if args.no_vad:
        cmd.append("--no-vad")
    if args.detect_language:
        cmd.append("--detect-language")
    return cmd


def _run_cuda_worker(args: argparse.Namespace) -> subprocess.CompletedProcess[str] | None:
    """Run a CUDA operation in a child process so native crashes are observable."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = _worker_command(args, "cuda")
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=CUDA_WORKER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return subprocess.CompletedProcess(cmd, 124, stdout=stdout, stderr=stderr)


def _print_child_output(result: subprocess.CompletedProcess[str]) -> None:
    """Relay child stdout/stderr to the parent streams."""
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def _cuda_failure_report(
    args: argparse.Namespace,
    result: subprocess.CompletedProcess[str],
) -> str:
    operation = _operation_name(args)
    resolved_device, resolved_compute = resolve_device("cuda")
    if args.compute_type != "default":
        resolved_compute = args.compute_type
    diagnostics = collect_cuda_diagnostics(
        device=resolved_device,
        compute_type=resolved_compute,
        model_name="base" if args.detect_language else args.model,
        operation=operation,
    )
    failure_class = classify_worker_failure(
        result.returncode,
        result.stdout or "",
        result.stderr or "",
        timed_out=result.returncode == 124,
    )
    return format_cuda_failure_report(
        operation=operation,
        failure_class=failure_class,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        diagnostics=diagnostics,
    )


def _run_parent(args: argparse.Namespace) -> None:
    """Run the CLI, isolating CUDA so native crashes cannot be silent."""
    if args.device == "cpu":
        _run_cli(args)
        return

    result = _run_cuda_worker(args)
    if result is None:
        print("Internal error: CUDA worker did not return a result.", file=sys.stderr)
        sys.exit(1)

    if result.returncode == 0:
        _print_child_output(result)
        return

    report = _cuda_failure_report(args, result)
    if args.device == "cuda":
        print(report, file=sys.stderr)
        sys.exit(1)

    print(report, file=sys.stderr)
    print(
        "WARNING: CUDA inference failed under --device auto; retrying on CPU.",
        file=sys.stderr,
    )
    args.device = "cpu"
    _run_cli(args)


def _run_worker(args: argparse.Namespace) -> None:
    """Run child worker code with Python exception reporting enabled."""
    with contextlib.suppress(Exception):
        faulthandler.enable(all_threads=True)
    try:
        _run_cli(args)
    except BaseException as exc:
        print(
            f"{PYTHON_EXCEPTION_MARKER}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio using faster-whisper")
    _add_arguments(parser)
    args = parser.parse_args()

    ensure_runtime_dependencies()

    if args._video2pr_worker:
        _run_worker(args)
        return

    _run_parent(args)


if __name__ == "__main__":
    main()
