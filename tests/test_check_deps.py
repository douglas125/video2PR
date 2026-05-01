"""Tests for scripts/check_deps.py - conda path discovery and JSON parsing."""

import os
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_deps


class TestFindConda:
    """Tests for find_conda() path discovery."""

    def test_which_finds_conda_returns_immediately(self):
        """When shutil.which finds conda, return it on any platform."""
        with patch("check_deps.shutil.which", return_value="/usr/bin/conda"):
            result = check_deps.find_conda()
        assert result == "/usr/bin/conda"

    def test_which_finds_conda_on_windows(self):
        """When shutil.which finds conda on Windows, return it without fallback."""
        with (
            patch(
                "check_deps.shutil.which", return_value=r"C:\Users\me\miniconda3\condabin\conda.bat"
            ),
            patch("check_deps.platform.system", return_value="Windows"),
        ):
            result = check_deps.find_conda()
        assert result == r"C:\Users\me\miniconda3\condabin\conda.bat"

    def test_not_on_path_non_windows_returns_none(self):
        """On non-Windows, if shutil.which fails, return None."""
        with (
            patch("check_deps.shutil.which", return_value=None),
            patch("check_deps.platform.system", return_value="Linux"),
        ):
            result = check_deps.find_conda()
        assert result is None

    def test_not_on_path_macos_returns_none(self):
        """On macOS, if shutil.which fails, return None."""
        with (
            patch("check_deps.shutil.which", return_value=None),
            patch("check_deps.platform.system", return_value="Darwin"),
        ):
            result = check_deps.find_conda()
        assert result is None

    def test_windows_fallback_miniconda3(self, tmp_path):
        """On Windows, find conda.bat in ~/miniconda3/condabin/."""
        condabin = tmp_path / "miniconda3" / "condabin"
        condabin.mkdir(parents=True)
        conda_bat = condabin / "conda.bat"
        conda_bat.touch()

        with (
            patch("check_deps.shutil.which", return_value=None),
            patch("check_deps.platform.system", return_value="Windows"),
            patch("check_deps.Path.home", return_value=tmp_path),
        ):
            result = check_deps.find_conda()
        assert result == str(conda_bat)

    def test_windows_fallback_anaconda3(self, tmp_path):
        """On Windows, find conda.bat in ~/anaconda3/condabin/."""
        condabin = tmp_path / "anaconda3" / "condabin"
        condabin.mkdir(parents=True)
        conda_bat = condabin / "conda.bat"
        conda_bat.touch()

        with (
            patch("check_deps.shutil.which", return_value=None),
            patch("check_deps.platform.system", return_value="Windows"),
            patch("check_deps.Path.home", return_value=tmp_path),
        ):
            result = check_deps.find_conda()
        assert result == str(conda_bat)

    def test_windows_no_fallback_found(self, tmp_path):
        """On Windows with no conda anywhere, return None."""
        with (
            patch("check_deps.shutil.which", return_value=None),
            patch("check_deps.platform.system", return_value="Windows"),
            patch("check_deps.Path.home", return_value=tmp_path),
        ):
            result = check_deps.find_conda()
        assert result is None


def test_parse_json_output_accepts_banner_wrapped_json():
    output = 'banner line\n{"ffmpeg": true, "ffprobe": true}\ntrailer line\n'
    assert check_deps.parse_json_output(output) == {
        "ffmpeg": True,
        "ffprobe": True,
    }


def test_parse_json_output_pretty_printed_windows_env_list():
    """conda env list --json on Windows emits pretty-printed JSON; lines like
    a bare quoted path are themselves valid JSON strings and must NOT be
    returned as the parsed payload."""
    output = (
        "{\n"
        '  "envs": [\n'
        '    "C:\\\\Users\\\\foo\\\\miniconda3",\n'
        '    "C:\\\\Users\\\\foo\\\\miniconda3\\\\envs\\\\video2pr"\n'
        "  ],\n"
        '  "envs_dirs": [\n'
        '    "C:\\\\Users\\\\foo\\\\miniconda3\\\\envs"\n'
        "  ]\n"
        "}\n"
    )
    payload = check_deps.parse_json_output(output)
    assert isinstance(payload, dict)
    assert payload["envs"] == [
        "C:\\Users\\foo\\miniconda3",
        "C:\\Users\\foo\\miniconda3\\envs\\video2pr",
    ]


def test_parse_json_output_pretty_printed_unix_env_list():
    output = (
        "{\n"
        '  "envs": [\n'
        '    "/home/foo/miniconda3",\n'
        '    "/home/foo/miniconda3/envs/video2pr"\n'
        "  ]\n"
        "}\n"
    )
    payload = check_deps.parse_json_output(output)
    assert isinstance(payload, dict)
    assert "/home/foo/miniconda3/envs/video2pr" in payload["envs"]


def test_parse_json_output_pretty_printed_macos_env_list():
    output = (
        "{\n"
        '  "envs": [\n'
        '    "/Users/foo/miniconda3",\n'
        '    "/Users/foo/miniconda3/envs/video2pr"\n'
        "  ]\n"
        "}\n"
    )
    payload = check_deps.parse_json_output(output)
    assert isinstance(payload, dict)
    assert "/Users/foo/miniconda3/envs/video2pr" in payload["envs"]


def test_parse_json_output_returns_none_for_no_json():
    assert check_deps.parse_json_output("nothing here\nor here\n") is None


@pytest.mark.parametrize(
    "envs_json",
    [
        # Linux
        '"/home/foo/miniconda3",\n    "/home/foo/miniconda3/envs/video2pr"',
        # macOS
        '"/Users/foo/miniconda3",\n    "/Users/foo/miniconda3/envs/video2pr"',
    ],
)
def test_env_exists_pretty_printed_json_posix(envs_json):
    """Regression: pretty-printed `conda env list --json` must be parsed as a
    dict so env_exists correctly detects the video2pr environment."""
    stdout = f'{{\n  "envs": [\n    {envs_json}\n  ]\n}}\n'
    with patch(
        "check_deps.subprocess.run",
        return_value=CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=""),
    ):
        assert check_deps.env_exists("video2pr", "conda") is True


def test_env_exists_pretty_printed_json_windows():
    """Regression for the Windows-reported false negative: parse_json_output
    used to return the bare quoted path string from a pretty-printed line,
    causing env_exists to wrongly report the env missing.

    Patches Path -> PureWindowsPath inside check_deps so basename extraction
    works regardless of the host OS running the test."""
    from pathlib import PureWindowsPath

    stdout = (
        "{\n"
        '  "envs": [\n'
        '    "C:\\\\Users\\\\foo\\\\miniconda3",\n'
        '    "C:\\\\Users\\\\foo\\\\miniconda3\\\\envs\\\\video2pr"\n'
        "  ]\n"
        "}\n"
    )
    with (
        patch(
            "check_deps.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=""),
        ),
        patch("check_deps.Path", PureWindowsPath),
    ):
        assert check_deps.env_exists("video2pr", "conda") is True


def test_env_exists_missing_env():
    stdout = (
        "{\n"
        '  "envs": [\n'
        '    "/home/foo/miniconda3",\n'
        '    "/home/foo/miniconda3/envs/other"\n'
        "  ]\n"
        "}\n"
    )
    with patch(
        "check_deps.subprocess.run",
        return_value=CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=""),
    ):
        assert check_deps.env_exists("video2pr", "conda") is False


def test_check_deps_in_env_accepts_noisy_stdout():
    stdout = (
        "Preparing transaction...\n"
        '{"ffmpeg": true, "ffprobe": true, "faster-whisper": true, "python-docx": true}\n'
        "done\n"
    )
    with patch(
        "check_deps.subprocess.run",
        return_value=CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=""),
    ):
        result = check_deps.check_deps_in_env("conda")

    assert result == {
        "ffmpeg": True,
        "ffprobe": True,
        "faster-whisper": True,
        "python-docx": True,
    }


def test_check_deps_in_env_falls_back_when_json_missing():
    with patch(
        "check_deps.subprocess.run",
        return_value=CompletedProcess(
            args=[],
            returncode=0,
            stdout="banner only\nstill no json\n",
            stderr="",
        ),
    ):
        result = check_deps.check_deps_in_env("conda")

    assert result == {
        "ffmpeg": False,
        "ffprobe": False,
        "faster-whisper": False,
        "python-docx": False,
    }


def test_check_deps_in_env_uses_temp_file_not_dash_c():
    """Regression: the conda invocation must pass a script *file* path, not
    a multi-line `-c <script>` argument. On Windows, conda is a .bat wrapper
    invoked via cmd.exe, which mangles newline-bearing arguments and silently
    produces empty stdout — making every dep look missing."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["script_existed_during_call"] = os.path.exists(args[-1])
        return CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"ffmpeg": true, "ffprobe": true,'
            ' "faster-whisper": true, "python-docx": true}\n',
            stderr="",
        )

    with patch("check_deps.subprocess.run", side_effect=fake_run):
        check_deps.check_deps_in_env("conda")

    args = captured["args"]
    assert "-c" not in args, f"check_deps_in_env must not pass `-c <script>`; got {args}"
    assert args[-1].endswith(".py"), f"expected a .py temp file path, got {args[-1]!r}"
    assert captured["script_existed_during_call"], (
        "the temp script file must exist on disk while subprocess.run is invoked"
    )


def test_check_deps_in_env_cleans_up_temp_file():
    """The temp script file must be unlinked after the call returns."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["tmp_path"] = args[-1]
        return CompletedProcess(args=args, returncode=0, stdout="{}\n", stderr="")

    with patch("check_deps.subprocess.run", side_effect=fake_run):
        check_deps.check_deps_in_env("conda")

    assert not os.path.exists(captured["tmp_path"]), (
        f"temp script file {captured['tmp_path']!r} was not cleaned up"
    )


def test_check_deps_in_env_cleans_up_temp_file_on_subprocess_error():
    """Cleanup must run even if subprocess.run raises."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["tmp_path"] = args[-1]
        raise OSError("simulated subprocess failure")

    with (
        patch("check_deps.subprocess.run", side_effect=fake_run),
        pytest.raises(OSError),
    ):
        check_deps.check_deps_in_env("conda")

    assert not os.path.exists(captured["tmp_path"]), (
        f"temp script file {captured['tmp_path']!r} was not cleaned up after error"
    )


def test_main_parses_gpu_json_with_banner(capsys):
    gpu_stdout = (
        "preparing...\n"
        '{"device": "cuda", "gpu_name": "RTX 4090", "cuda_version": "12.4", '
        '"gpu_available": true, "install_command": null}\n'
    )
    deps = {"ffmpeg": True, "ffprobe": True, "faster-whisper": True, "python-docx": True}

    with (
        patch("check_deps.find_conda", return_value="conda"),
        patch("check_deps.env_exists", return_value=True),
        patch("check_deps.check_deps_in_env", return_value=deps),
        patch(
            "check_deps.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout=gpu_stdout, stderr=""),
        ),
    ):
        check_deps.main()

    out = capsys.readouterr().out
    assert "GPU: RTX 4090 (CUDA 12.4) — OK" in out
