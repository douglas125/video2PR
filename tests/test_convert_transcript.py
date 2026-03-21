"""Tests for scripts/convert_transcript.py."""

import json

import pytest

from conftest import import_script

ct = import_script("convert_transcript.py")


# ── SBV timestamp parsing ──────────────────────────────────────────


def test_sbv_timestamp_zero():
    assert ct.parse_sbv_timestamp("0:00:00.000") == 0.0


def test_sbv_timestamp_with_hours():
    assert ct.parse_sbv_timestamp("1:23:45.678") == pytest.approx(5025.678)


def test_sbv_timestamp_invalid():
    assert ct.parse_sbv_timestamp("invalid") == 0.0


# ── VTT timestamp parsing ──────────────────────────────────────────


def test_vtt_timestamp_hh_mm_ss():
    assert ct.parse_vtt_timestamp("01:23:45.678") == pytest.approx(5025.678)


def test_vtt_timestamp_mm_ss():
    assert ct.parse_vtt_timestamp("01:30.500") == pytest.approx(90.5)


# ── SBV parsing ─────────────────────────────────────────────────────


def test_parse_sbv_with_speaker():
    content = "0:00:00.000,0:00:05.000\nAlice: Hello world"
    segments = ct.parse_sbv(content)
    assert len(segments) == 1
    assert segments[0]["speaker"] == "Alice"
    assert segments[0]["text"] == "Hello world"


def test_parse_sbv_no_speaker():
    content = "0:00:00.000,0:00:05.000\nJust some text here"
    segments = ct.parse_sbv(content)
    assert len(segments) == 1
    assert segments[0]["speaker"] is None
    assert segments[0]["text"] == "Just some text here"


def test_parse_sbv_empty():
    assert ct.parse_sbv("") == []


# ── VTT parsing ─────────────────────────────────────────────────────


def test_parse_vtt_with_v_tag():
    content = (
        "00:00:01.000 --> 00:00:05.000\n"
        "<v Speaker>Some text</v>"
    )
    segments = ct.parse_vtt(content)
    assert len(segments) == 1
    assert segments[0]["speaker"] == "Speaker"
    assert segments[0]["text"] == "Some text"


def test_parse_vtt_strips_header():
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:05.000\n"
        "Hello world"
    )
    segments = ct.parse_vtt(content)
    assert len(segments) == 1
    assert segments[0]["text"] == "Hello world"


# ── Google TXT parsing ──────────────────────────────────────────────


def test_parse_google_txt_two_speakers():
    content = (
        "Alice (0:00:10)\n"
        "First message\n"
        "Bob (0:00:30)\n"
        "Second message"
    )
    segments = ct.parse_google_txt(content)
    assert len(segments) == 2
    assert segments[0]["speaker"] == "Alice"
    assert segments[0]["start"] == 10.0
    # First segment end == second segment start
    assert segments[0]["end"] == 30.0
    assert segments[1]["speaker"] == "Bob"


def test_parse_google_txt_last_segment_end():
    content = "Alice (0:01:00)\nSome text"
    segments = ct.parse_google_txt(content)
    assert len(segments) == 1
    assert segments[0]["end"] == 90.0  # start(60) + 30


# ── Format detection ────────────────────────────────────────────────


def test_detect_format_by_extension(tmp_path):
    sbv = tmp_path / "test.sbv"
    sbv.write_text("0:00:00.000,0:00:05.000\ntext")
    assert ct.detect_format(sbv) == "sbv"

    docx = tmp_path / "test.docx"
    docx.write_text("")  # extension is enough
    assert ct.detect_format(docx) == "teams_docx"

    vtt = tmp_path / "test.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:05.000\ntext")
    assert ct.detect_format(vtt) == "vtt"


def test_convert_writes_utf8_json(tmp_path):
    transcript = tmp_path / "meeting.txt"
    transcript.write_text("José (0:00:01)\nnegócio e migração", encoding="utf-8")
    output_dir = tmp_path / "out"

    ct.convert(transcript, output_dir, "google_txt")

    transcript_json = json.loads((output_dir / "transcript.json").read_text(encoding="utf-8"))
    meta_json = json.loads(
        (output_dir / "external_transcript_meta.json").read_text(encoding="utf-8")
    )

    assert transcript_json["segments"][0]["speaker"] == "José"
    assert transcript_json["segments"][0]["text"] == "negócio e migração"
    assert meta_json["original_file"] == "meeting.txt"
