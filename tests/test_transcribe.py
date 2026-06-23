"""Tests for scripts/transcribe.py — pure function tests only."""

import argparse
import json
import subprocess

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


def _args(device="auto"):
    return argparse.Namespace(
        input="audio.wav",
        output_dir=None,
        model="small",
        language=None,
        device=device,
        compute_type="default",
        no_vad=False,
        detect_language=True,
        _video2pr_worker=False,
    )


def _fake_diagnostics():
    return {
        "selected_device": "cuda",
        "selected_compute_type": "float16",
        "model": "base",
        "packages": {"faster-whisper": "1.2.1", "ctranslate2": "4.7.1"},
        "ctranslate2": {"cuda_supported_compute_types": ["float16"]},
        "nvidia_smi": {
            "gpu_name": "RTX 4070 Laptop GPU",
            "driver_version": "596.08",
            "cuda_version": "13.2",
        },
        "windows_dll_path_hints": {},
    }


def test_device_auto_falls_back_to_cpu_when_cuda_worker_native_crashes(monkeypatch, capsys):
    args = _args(device="auto")
    calls = []

    monkeypatch.setattr(tr, "_auto_should_try_cuda", lambda: True)
    monkeypatch.setattr(
        tr,
        "_run_cuda_worker",
        lambda args: subprocess.CompletedProcess(
            args=[],
            returncode=3221226505,
            stdout="Loading Whisper model 'base' (device=cuda, compute=float16)...\n",
            stderr="",
        ),
    )
    monkeypatch.setattr(tr, "collect_cuda_diagnostics", lambda **kwargs: _fake_diagnostics())

    def fake_run_cli(run_args):
        calls.append(run_args.device)
        print('{"language": "pt", "confidence": 0.96}')

    monkeypatch.setattr(tr, "_run_cli", fake_run_cli)

    tr._run_parent(args)

    captured = capsys.readouterr()
    assert calls == ["cpu"]
    assert "failure_class: native_crash" in captured.err
    assert "0xC0000409" in captured.err
    assert "signed -1073740791" in captured.err
    assert "retrying on CPU" in captured.err
    assert '"language": "pt"' in captured.out


def test_device_auto_skips_cuda_worker_when_cuda_is_not_candidate(monkeypatch):
    args = _args(device="auto")
    calls = []

    monkeypatch.setattr(tr, "_auto_should_try_cuda", lambda: False)

    def fail_cuda_worker(run_args):
        raise AssertionError("auto should not force cuda on CPU-only hosts")

    def fake_run_cli(run_args):
        calls.append(run_args.device)

    monkeypatch.setattr(tr, "_run_cuda_worker", fail_cuda_worker)
    monkeypatch.setattr(tr, "_run_cli", fake_run_cli)

    tr._run_parent(args)

    assert calls == ["auto"]


def test_device_auto_prefers_cuda_worker_when_cuda_is_candidate(monkeypatch, capsys):
    args = _args(device="auto")
    calls = []

    monkeypatch.setattr(tr, "_auto_should_try_cuda", lambda: True)
    monkeypatch.setattr(
        tr,
        "_run_cuda_worker",
        lambda args: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"language": "pt", "confidence": 0.96}\n',
            stderr="",
        ),
    )

    def fake_run_cli(run_args):
        calls.append(run_args.device)

    monkeypatch.setattr(tr, "_run_cli", fake_run_cli)

    tr._run_parent(args)

    captured = capsys.readouterr()
    assert calls == []
    assert '"language": "pt"' in captured.out


def test_device_cuda_fails_loudly_when_worker_native_crashes(monkeypatch, capsys):
    args = _args(device="cuda")

    monkeypatch.setattr(
        tr,
        "_run_cuda_worker",
        lambda args: subprocess.CompletedProcess(
            args=[],
            returncode=-1073740791,
            stdout="Loading Whisper model 'base' (device=cuda, compute=float16)...\n",
            stderr="",
        ),
    )
    monkeypatch.setattr(tr, "collect_cuda_diagnostics", lambda **kwargs: _fake_diagnostics())

    with pytest.raises(SystemExit) as exc_info:
        tr._run_parent(args)

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "CUDA inference failed." in captured.err
    assert "failure_class: native_crash" in captured.err
    assert "child_stdout_tail" in captured.err


def test_worker_prints_python_exception_marker(monkeypatch, capsys):
    args = _args(device="cuda")

    def raise_error(run_args):
        raise RuntimeError("cuda load failed")

    monkeypatch.setattr(tr, "_run_cli", raise_error)

    with pytest.raises(SystemExit) as exc_info:
        tr._run_worker(args)

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert tr.PYTHON_EXCEPTION_MARKER in captured.err
    assert "RuntimeError: cuda load failed" in captured.err


def test_missing_runtime_dependency_points_to_video2pr_env(monkeypatch, capsys):
    monkeypatch.setattr(tr.importlib.util, "find_spec", lambda module_name: None)

    with pytest.raises(SystemExit) as exc_info:
        tr.ensure_runtime_dependencies()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Missing runtime dependency: faster-whisper" in captured.err
    assert "conda run -n video2pr" in captured.err


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
