"""Tests for scripts/extract_frame.py — pure function tests only."""

from conftest import import_script

ef = import_script("extract_frame.py")


def test_normalize_hh_mm_ss():
    assert ef.normalize_timestamp("01:23:45") == "01:23:45"


def test_normalize_mm_ss():
    assert ef.normalize_timestamp("5:30") == "00:05:30"


def test_normalize_seconds_int():
    assert ef.normalize_timestamp("90") == "00:01:30"


def test_normalize_seconds_float():
    assert ef.normalize_timestamp("3661.5") == "01:01:01"


def test_timestamp_to_filename():
    assert ef.timestamp_to_filename("01:23:45") == "frame_01h23m45s.png"


def test_timestamp_to_filename_zeros():
    assert ef.timestamp_to_filename("00:00:00") == "frame_00h00m00s.png"
