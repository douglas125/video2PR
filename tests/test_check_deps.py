"""Tests for scripts/check_deps.py - conda path discovery and JSON parsing."""

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
            patch("check_deps.shutil.which", return_value=r"C:\Users\me\miniconda3\condabin\conda.bat"),
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


def test_check_deps_in_env_accepts_noisy_stdout():
    stdout = (
        "Preparing transaction...\n"
        '{"ffmpeg": true, "ffprobe": true, "whisper": true, "python-docx": true}\n'
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
        "whisper": True,
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
        "whisper": False,
        "python-docx": False,
    }


def test_main_parses_gpu_json_with_banner(capsys):
    gpu_stdout = (
        "preparing...\n"
        '{"device": "cuda", "gpu_name": "RTX 4090", "cuda_version": "12.4", '
        '"torch_device_available": true, "install_command": null}\n'
    )
    deps = {"ffmpeg": True, "ffprobe": True, "whisper": True, "python-docx": True}

    with (
        patch("check_deps.find_conda", return_value="conda"),
        patch("check_deps.env_exists", return_value=True),
        patch("check_deps.check_deps_in_env", return_value=deps),
        patch(
            "check_deps.subprocess.run",
            return_value=CompletedProcess(
                args=[], returncode=0, stdout=gpu_stdout, stderr=""
            ),
        ),
    ):
        check_deps.main()

    out = capsys.readouterr().out
    assert "GPU: RTX 4090 (CUDA 12.4) — OK" in out
