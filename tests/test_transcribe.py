"""Tests for scripts/transcribe.py — pure function tests only."""

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


# ── SRT offsetting ──────────────────────────────────────────────────


def test_offset_srt_shifts_timestamps():
    srt = (
        "1\n"
        "00:00:10,000 --> 00:00:20,000\n"
        "Hello\n\n"
        "2\n"
        "00:00:30,000 --> 00:00:40,000\n"
        "World\n"
    )
    result, _ = tr.offset_srt(srt, 60.0, 1)
    assert "00:01:10,000 --> 00:01:20,000" in result
    assert "00:01:30,000 --> 00:01:40,000" in result


def test_offset_srt_renumbers():
    srt = (
        "1\n"
        "00:00:10,000 --> 00:00:20,000\n"
        "Hello\n\n"
        "2\n"
        "00:00:30,000 --> 00:00:40,000\n"
        "World\n"
    )
    result, _ = tr.offset_srt(srt, 0.0, 5)
    lines = result.strip().split("\n")
    assert lines[0] == "5"


def test_offset_srt_returns_next_index():
    srt = (
        "1\n"
        "00:00:10,000 --> 00:00:20,000\n"
        "Hello\n\n"
        "2\n"
        "00:00:30,000 --> 00:00:40,000\n"
        "World\n"
    )
    _, next_idx = tr.offset_srt(srt, 0.0, 1)
    assert next_idx == 3


# ── JSON segment offsetting ─────────────────────────────────────────


def test_offset_json_basic():
    segments = [
        {
            "start": 10.0,
            "end": 20.0,
            "text": "Hello",
            "words": [
                {"start": 10.0, "end": 15.0, "word": "Hello"},
            ],
        }
    ]
    result = tr.offset_json_segments(segments, 120.0)
    assert result[0]["start"] == pytest.approx(130.0)
    assert result[0]["end"] == pytest.approx(140.0)
    assert result[0]["words"][0]["start"] == pytest.approx(130.0)


def test_offset_json_no_words():
    segments = [{"start": 5.0, "end": 10.0, "text": "No words key"}]
    result = tr.offset_json_segments(segments, 100.0)
    assert result[0]["start"] == pytest.approx(105.0)
    assert "words" not in result[0]


# ── Elapsed formatting ──────────────────────────────────────────────


def test_format_elapsed():
    assert tr.format_elapsed(45.3) == "45.3s"
    assert tr.format_elapsed(125.7) == "2m 5.7s"
