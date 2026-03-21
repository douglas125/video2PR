"""Tests for scripts/check_deps.py — conda path discovery."""

import sys
from pathlib import Path
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
