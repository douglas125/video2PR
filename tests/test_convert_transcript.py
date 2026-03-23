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
    segments = ct.parse_teams_vtt(content)
    assert len(segments) == 1
    assert segments[0]["speaker"] == "Speaker"
    assert segments[0]["text"] == "Some text"


def test_parse_vtt_strips_header():
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:05.000\n"
        "Hello world"
    )
    segments = ct.parse_teams_vtt(content)
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
    assert ct.detect_format(vtt) == "zoom_vtt"  # generic VTT defaults to zoom parser


def test_detect_format_teams_vtt(tmp_path):
    vtt = tmp_path / "teams.vtt"
    vtt.write_text(
        "WEBVTT\nKind: captions\nLanguage: en\n\n"
        "abc123\n00:00:01.000 --> 00:00:05.000\n"
        "<v Douglas Castilho>Hello everyone.</v>"
    )
    assert ct.detect_format(vtt) == "teams_vtt"


def test_detect_format_zoom_vtt(tmp_path):
    vtt = tmp_path / "zoom.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "1\n00:00:00.000 --> 00:00:04.560\n"
        "Douglas Castilho: Good morning everyone."
    )
    assert ct.detect_format(vtt) == "zoom_vtt"


def test_detect_format_zoom_txt(tmp_path):
    txt = tmp_path / "zoom.txt"
    txt.write_text(
        "Douglas Castilho   00:00:00\n"
        "Good morning everyone, let's get started.\n\n"
        "Jane Smith   00:00:04\n"
        "Sure. I finished the API refactor yesterday."
    )
    assert ct.detect_format(txt) == "zoom_txt"


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


# ── Zoom VTT parsing ──────────────────────────────────────────────


ZOOM_VTT_REALISTIC = """\
WEBVTT

1
00:00:00.000 --> 00:00:04.560
Douglas Castilho: Good morning everyone, let's get started with the standup.

2
00:00:04.560 --> 00:00:09.120
Jane Smith: Sure. I finished the API refactor yesterday and pushed the branch.

3
00:00:09.120 --> 00:00:15.840
Douglas Castilho: Great. Any blockers?

4
00:00:15.840 --> 00:00:25.200
Jane Smith: Not really, but I noticed the authentication middleware is getting slow. We should look into caching the JWT validation.

5
00:00:25.200 --> 00:00:32.500
Bob Johnson: I can take that. I was already looking at the token cache implementation last week.

6
00:00:32.500 --> 00:00:40.100
Douglas Castilho: Perfect. Bob, can you create a ticket for that? Let's aim to have it done by Friday.

7
00:00:40.100 --> 00:00:48.750
María García: I have an update on the database migration. The schema changes are ready but I need someone to review the rollback script.

8
00:00:48.750 --> 00:00:55.000
Douglas Castilho: I'll review it this afternoon. Send me the PR link.

9
00:00:55.000 --> 00:01:05.200
Bob Johnson: One more thing — the CI pipeline has been flaky. About 20% of runs fail on the integration tests.

10
00:01:05.200 --> 00:01:12.800
Jane Smith: That's the Docker container timing issue. I filed a bug last week: JIRA-1234.

11
00:01:12.800 --> 00:01:18.000
Douglas Castilho: OK, let's prioritize that. Flaky CI wastes everyone's time. Anything else?
"""


def test_parse_zoom_vtt_multi_speaker():
    segments = ct.parse_zoom_vtt(ZOOM_VTT_REALISTIC)
    assert len(segments) == 11

    # Check speaker attribution
    assert segments[0]["speaker"] == "Douglas Castilho"
    assert segments[1]["speaker"] == "Jane Smith"
    assert segments[4]["speaker"] == "Bob Johnson"
    assert segments[6]["speaker"] == "María García"

    # Check text is stripped of speaker prefix
    assert segments[0]["text"] == "Good morning everyone, let's get started with the standup."
    assert "Douglas Castilho:" not in segments[0]["text"]

    # Check timestamps
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == pytest.approx(4.56)
    assert segments[10]["start"] == pytest.approx(72.8)


def test_parse_zoom_vtt_no_speakers():
    content = (
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:05.000\n"
        "just some text without a speaker prefix\n\n"
        "2\n00:00:05.000 --> 00:00:10.000\n"
        "more text here"
    )
    segments = ct.parse_zoom_vtt(content)
    assert len(segments) == 2
    assert segments[0]["speaker"] is None
    assert segments[0]["text"] == "just some text without a speaker prefix"


def test_parse_zoom_vtt_avoids_label_false_positive():
    """Text like 'Note: something' should not be treated as a speaker."""
    content = (
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:05.000\n"
        "note: this is a note, not a speaker"
    )
    segments = ct.parse_zoom_vtt(content)
    assert len(segments) == 1
    assert segments[0]["speaker"] is None


def test_parse_zoom_vtt_utf8_names():
    content = (
        "WEBVTT\n\n"
        "1\n00:00:00.000 --> 00:00:05.000\n"
        "José da Silva: Vamos discutir o projeto de migração.\n\n"
        "2\n00:00:05.000 --> 00:00:10.000\n"
        "André Müller: Sim, concordo com a abordagem."
    )
    segments = ct.parse_zoom_vtt(content)
    assert len(segments) == 2
    assert segments[0]["speaker"] == "José da Silva"
    assert segments[1]["speaker"] == "André Müller"
    assert "migração" in segments[0]["text"]


def test_parse_zoom_vtt_single_speaker():
    content = (
        "WEBVTT\n\n"
        "1\n00:00:00.000 --> 00:00:10.000\n"
        "Speaker: First segment.\n\n"
        "2\n00:00:10.000 --> 00:00:20.000\n"
        "Speaker: Second segment."
    )
    segments = ct.parse_zoom_vtt(content)
    assert len(segments) == 2
    assert all(s["speaker"] == "Speaker" for s in segments)


# ── Zoom TXT parsing ──────────────────────────────────────────────


ZOOM_TXT_REALISTIC = """\
Douglas Castilho   00:00:00
Good morning everyone, let's get started with the standup.

Jane Smith   00:00:04
Sure. I finished the API refactor yesterday and pushed the branch.

Douglas Castilho   00:00:09
Great. Any blockers?

Jane Smith   00:00:15
Not really, but I noticed the authentication middleware is getting slow.
We should look into caching the JWT validation.

Bob Johnson   00:00:25
I can take that. I was already looking at the token cache implementation.

María García   00:00:40
I have an update on the database migration.
The schema changes are ready but I need someone to review the rollback script.

Douglas Castilho   00:00:48
I'll review it this afternoon. Send me the PR link.
"""


def test_parse_zoom_txt_multi_speaker():
    segments = ct.parse_zoom_txt(ZOOM_TXT_REALISTIC)
    assert len(segments) == 7

    # Check speakers
    assert segments[0]["speaker"] == "Douglas Castilho"
    assert segments[1]["speaker"] == "Jane Smith"
    assert segments[4]["speaker"] == "Bob Johnson"
    assert segments[5]["speaker"] == "María García"

    # Check timestamps (only start times in Zoom TXT)
    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] == 4.0

    # Check end time derivation (end = next segment's start)
    assert segments[0]["end"] == 4.0
    assert segments[5]["end"] == 48.0

    # Last segment: end = start + 30
    assert segments[6]["end"] == 78.0  # 48 + 30

    # Check multi-line text is captured
    assert "We should look into" in segments[3]["text"]


def test_parse_zoom_txt_single_entry():
    content = "Alice   00:01:00\nSome text here"
    segments = ct.parse_zoom_txt(content)
    assert len(segments) == 1
    assert segments[0]["speaker"] == "Alice"
    assert segments[0]["start"] == 60.0
    assert segments[0]["end"] == 90.0  # 60 + 30
    assert segments[0]["text"] == "Some text here"


def test_parse_zoom_txt_utf8(tmp_path):
    """Full pipeline: Zoom TXT with UTF-8 names through convert()."""
    transcript = tmp_path / "zoom_meeting.txt"
    transcript.write_text(
        "José da Silva   00:00:01\n"
        "negócio e migração do banco\n\n"
        "André Müller   00:00:10\n"
        "Ja, das ist richtig.",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    ct.convert(transcript, output_dir, "zoom_txt")

    data = json.loads((output_dir / "transcript.json").read_text(encoding="utf-8"))
    meta = json.loads((output_dir / "external_transcript_meta.json").read_text(encoding="utf-8"))

    assert data["segments"][0]["speaker"] == "José da Silva"
    assert "migração" in data["segments"][0]["text"]
    assert meta["source"] == "zoom_txt"
    assert meta["has_speakers"] is True
    assert meta["has_timestamps"] is True


def test_convert_zoom_vtt_pipeline(tmp_path):
    """Full pipeline: Zoom VTT through convert()."""
    transcript = tmp_path / "meeting.vtt"
    transcript.write_text(
        "WEBVTT\n\n"
        "1\n00:00:00.000 --> 00:00:05.000\n"
        "Alice: Hello everyone.\n\n"
        "2\n00:00:05.000 --> 00:00:10.000\n"
        "Bob: Hi Alice, ready to start?",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    ct.convert(transcript, output_dir, "zoom_vtt")

    data = json.loads((output_dir / "transcript.json").read_text(encoding="utf-8"))
    meta = json.loads((output_dir / "external_transcript_meta.json").read_text(encoding="utf-8"))

    assert len(data["segments"]) == 2
    assert data["segments"][0]["speaker"] == "Alice"
    assert data["segments"][1]["speaker"] == "Bob"
    assert meta["source"] == "zoom_vtt"
