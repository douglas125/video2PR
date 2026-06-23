"""End-to-end pipeline test: synthesize a tiny video, extract audio, transcribe.

Skipped automatically when ffmpeg or faster-whisper is not installed. Designed
to run in a dedicated CI job that installs both. The test does not assert that
transcription is accurate — silent audio yields zero segments. It asserts the
plumbing produces well-formed output files matching the documented schema.
"""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import import_script

extract_audio = import_script("extract_audio.py")
transcribe = import_script("transcribe.py")


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def _synthesize_video(path: Path, duration_s: int = 3) -> None:
    """Create a tiny silent MP4 with a black frame track for testing."""
    cmd = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=160x120:d={duration_s}",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono",
        "-t",
        str(duration_s),
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-y",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"ffmpeg failed: {result.stderr[-500:]}"


def test_extract_audio_pipeline(tmp_path):
    """extract_audio.extract_audio + get_metadata produce audio.wav + parseable metadata."""
    video = tmp_path / "test.mp4"
    _synthesize_video(video)

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    audio_path = extract_audio.extract_audio(video, out_dir)
    metadata = extract_audio.get_metadata(video)

    assert audio_path == out_dir / "audio.wav"
    assert audio_path.exists()
    assert audio_path.stat().st_size > 0
    assert "format" in metadata
    assert "streams" in metadata


@pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is None,
    reason="faster-whisper not installed",
)
def test_full_pipeline_produces_valid_transcript_json(tmp_path):
    """End-to-end: video → audio → transcript.json with the documented schema."""
    video = tmp_path / "test.mp4"
    _synthesize_video(video, duration_s=2)

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    audio_path = extract_audio.extract_audio(video, out_dir)
    assert audio_path.exists()

    transcribe.transcribe(
        audio_path=audio_path,
        output_dir=out_dir,
        model_name="base",
        device="cpu",
        compute_type="int8",
        language="en",
        vad_filter=True,
    )

    transcript_path = out_dir / "transcript.json"
    srt_path = out_dir / "transcript.srt"
    assert transcript_path.exists(), "transcript.json was not produced"
    assert srt_path.exists(), "transcript.srt was not produced"

    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert "segments" in payload
    assert isinstance(payload["segments"], list)

    for seg in payload["segments"]:
        assert "start" in seg and isinstance(seg["start"], int | float)
        assert "end" in seg and isinstance(seg["end"], int | float)
        assert "text" in seg and isinstance(seg["text"], str)
        assert "words" in seg and isinstance(seg["words"], list)
