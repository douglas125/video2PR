"""Tests for scripts/extract_frame.py â€” pure function tests only."""

import sys
from subprocess import CompletedProcess

import pytest
from conftest import import_script

ef = import_script("extract_frame.py")


def test_normalize_hh_mm_ss():
    assert ef.normalize_timestamp("01:23:45") == "01:23:45"


def test_normalize_mm_ss():
    assert ef.normalize_timestamp("5:30") == "00:05:30"


def test_normalize_seconds_int():
    assert ef.normalize_timestamp("90") == "00:01:30"


def test_normalize_seconds_float():
    assert ef.normalize_timestamp("3661.5") == "01:01:01.5"


def test_timestamp_to_filename():
    assert ef.timestamp_to_filename("01:23:45") == "frame_01h23m45s.png"


def test_timestamp_to_filename_zeros():
    assert ef.timestamp_to_filename("00:00:00") == "frame_00h00m00s.png"


@pytest.mark.parametrize("value", ["garbage", "-1", "nan", "inf", "00:60:00", "2:99"])
def test_invalid_timestamp_rejected(value):
    with pytest.raises(ValueError):
        ef.normalize_timestamp(value)


def test_fractional_names_are_distinct():
    assert ef.timestamp_to_filename("1.2") != ef.timestamp_to_filename("1.3")


def test_success_requires_frame_file(tmp_path, monkeypatch, capsys):
    video = tmp_path / "video.mp4"
    video.touch()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "extract_frame.py",
            "--input",
            str(video),
            "--output-dir",
            str(tmp_path / "out"),
            "--timestamp",
            "1000",
        ],
    )
    monkeypatch.setattr(ef.subprocess, "run", lambda *a, **kw: CompletedProcess([], 0, "", ""))
    with pytest.raises(SystemExit) as exc:
        ef.main()
    assert exc.value.code == 1
    assert "No frame produced" in capsys.readouterr().err
