"""Tests for scripts/check_gpu.py."""

import json
import subprocess
import sys
import types

from conftest import import_script

gpu = import_script("check_gpu.py")


# ── Helper to build a fake nvidia-smi ──────────────────────────────


def _fake_nvidia_smi(gpu_name="NVIDIA RTX 3080", driver="535.129.03", cuda_ver="12.4"):
    """Return a side_effect function for monkeypatching subprocess.run."""
    query_stdout = f"{gpu_name}, {driver}\n"
    header_stdout = (
        f"| NVIDIA-SMI {driver}   Driver Version: {driver}"
        f"   CUDA Version: {cuda_ver}  |\n"
    )

    def fake_run(cmd, **kwargs):
        if any("--query-gpu" in arg for arg in cmd):
            return subprocess.CompletedProcess(cmd, 0, stdout=query_stdout, stderr="")
        # Plain nvidia-smi (header)
        return subprocess.CompletedProcess(cmd, 0, stdout=header_stdout, stderr="")

    return fake_run


def _nvidia_smi_missing(cmd, **kwargs):
    raise FileNotFoundError("nvidia-smi not found")


# ── Tests ──────────────────────────────────────────────────────────


def test_nvidia_cuda_working(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", _fake_nvidia_smi())

    # Mock ctranslate2 with CUDA support
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: ["float16", "int8"] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    result = gpu.check_gpu()
    assert result["device"] == "cuda"
    assert result["gpu_available"] is True
    assert result["install_command"] is None
    assert result["gpu_name"] == "NVIDIA RTX 3080"
    assert result["cuda_version"] == "12.4"


def test_nvidia_ct2_cpu_only(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", _fake_nvidia_smi())

    # Mock ctranslate2 without CUDA support
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: [] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    result = gpu.check_gpu()
    assert result["device"] == "cpu"
    assert result["gpu_available"] is False
    assert result["install_command"] is not None


def test_nvidia_ct2_missing(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", _fake_nvidia_smi())

    # ctranslate2 not installed
    monkeypatch.setitem(sys.modules, "ctranslate2", None)

    result = gpu.check_gpu()
    assert result["ct2_installed"] is False
    assert result["install_command"] is not None


def test_apple_silicon(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: [] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    result = gpu.check_gpu()
    assert result["device"] == "cpu"
    assert result["gpu_available"] is False
    assert result["install_command"] is None
    assert "Apple Silicon" in result["message"]


def test_cpu_only_no_gpu(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: [] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    result = gpu.check_gpu()
    assert result["device"] == "cpu"
    assert result["install_command"] is None


def test_nvidia_smi_parse_error(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/nvidia-smi")

    def garbage_nvidia_smi(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="garbage output\n", stderr="")

    monkeypatch.setattr(subprocess, "run", garbage_nvidia_smi)

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: [] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    # Should not crash
    result = gpu.check_gpu()
    assert result["device"] == "cpu"


def test_json_output(monkeypatch, capsys):
    """check_gpu.py main() outputs valid JSON."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: [] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    gpu.main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "device" in data
    assert "message" in data
    assert "gpu_available" in data


def test_windows_nvidia_smi_path(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    monkeypatch.setattr("shutil.which", lambda x: None)

    # Monkeypatch the helpers to simulate Windows detection results
    monkeypatch.setattr(
        gpu, "_run_nvidia_smi_query", lambda: ("NVIDIA RTX 4090", "545.0")
    )
    monkeypatch.setattr(gpu, "_parse_cuda_version", lambda: "12.4")

    # CTranslate2 without CUDA
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_supported_compute_types = lambda device: [] if device == "cuda" else ["int8"]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    result = gpu.check_gpu()
    assert result["gpu_name"] == "NVIDIA RTX 4090"
    assert result["install_command"] is not None
