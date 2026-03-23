"""Tests for scripts/transcribe.py — pure function tests only."""

import json

import pytest

from conftest import import_script

tr = import_script("transcribe.py")


# ── SRT timestamp round-trips ──────────────────────────────────────


def test_parse_srt_timestamp():
    assert tr.parse_srt_timestamp("01:23:45,678") == pytest.approx(5025.678)


def test_format_srt_timestamp():
    assert tr.format_srt_timestamp(5025.5) == "01:23:45,500"


def test_srt_timestamp_roundtrip():
    for ts in ["00:00:00,000", "00:05:30,500", "02:00:00,000"]:
        assert tr.format_srt_timestamp(tr.parse_srt_timestamp(ts)) == ts


def test_parse_srt_invalid():
    assert tr.parse_srt_timestamp("invalid") == 0.0


# ── Elapsed formatting ──────────────────────────────────────────────


def test_format_elapsed():
    assert tr.format_elapsed(45.3) == "45.3s"
    assert tr.format_elapsed(125.7) == "2m 5.7s"


# ── Device resolution ──────────────────────────────────────────────


def test_resolve_device_auto():
    device, compute = tr.resolve_device("auto")
    assert device == "auto"
    assert compute == "default"


def test_resolve_device_cuda():
    device, compute = tr.resolve_device("cuda")
    assert device == "cuda"
    assert compute == "float16"


def test_resolve_device_cpu():
    device, compute = tr.resolve_device("cpu")
    assert device == "cpu"
    assert compute == "int8"


# ── Custom SRT writer ──────────────────────────────────────────────


def test_write_transcript_srt(tmp_path):
    segments = [
        {
            "start": 0.0,
            "end": 3.5,
            "text": "Hello everyone, welcome to the meeting.",
            "words": [],
        },
        {
            "start": 3.5,
            "end": 8.2,
            "text": "Today we'll discuss the new API design.",
            "words": [],
        },
        {
            "start": 10.0,
            "end": 15.0,
            "text": "Let's start with the authentication module.",
            "words": [],
        },
    ]

    srt_path = tmp_path / "transcript.srt"
    tr.write_transcript_srt(srt_path, segments)

    content = srt_path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")

    # First subtitle
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:03,500"
    assert lines[2] == "Hello everyone, welcome to the meeting."

    # Second subtitle
    assert lines[4] == "2"
    assert lines[5] == "00:00:03,500 --> 00:00:08,200"

    # Third subtitle
    assert lines[8] == "3"
    assert lines[9] == "00:00:10,000 --> 00:00:15,000"


def test_write_transcript_srt_long_timestamps(tmp_path):
    """Test SRT writer with timestamps over 1 hour."""
    segments = [
        {
            "start": 3661.5,
            "end": 3670.0,
            "text": "We've been at this for an hour.",
            "words": [],
        },
    ]
    srt_path = tmp_path / "transcript.srt"
    tr.write_transcript_srt(srt_path, segments)
    content = srt_path.read_text(encoding="utf-8")
    assert "01:01:01,500 --> 01:01:10,000" in content


# ── Custom JSON writer ─────────────────────────────────────────────


def test_write_transcript_json(tmp_path):
    segments = [
        {
            "start": 0.0,
            "end": 5.2,
            "text": "Hello everyone.",
            "words": [
                {"word": "Hello", "start": 0.08, "end": 0.52, "probability": 0.95},
                {"word": "everyone.", "start": 0.55, "end": 1.18, "probability": 0.89},
            ],
        },
        {
            "start": 5.5,
            "end": 12.0,
            "text": "Let's review the sprint backlog and discuss priorities.",
            "words": [
                {"word": "Let's", "start": 5.5, "end": 5.8, "probability": 0.92},
                {"word": "review", "start": 5.85, "end": 6.3, "probability": 0.97},
            ],
        },
    ]

    json_path = tmp_path / "transcript.json"
    tr.write_transcript_json(json_path, segments)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "segments" in data
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "Hello everyone."
    assert data["segments"][0]["words"][0]["probability"] == 0.95
    assert data["segments"][1]["start"] == 5.5


def test_write_transcript_json_utf8(tmp_path):
    """Test JSON writer with non-ASCII characters."""
    segments = [
        {
            "start": 0.0,
            "end": 5.0,
            "text": "Vamos discutir a migração do banco de dados.",
            "words": [],
        },
    ]
    json_path = tmp_path / "transcript.json"
    tr.write_transcript_json(json_path, segments)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "migração" in data["segments"][0]["text"]


def test_write_transcript_json_empty_segments(tmp_path):
    """Test JSON writer with empty segment list."""
    json_path = tmp_path / "transcript.json"
    tr.write_transcript_json(json_path, [])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data == {"segments": []}
