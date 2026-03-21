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

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    result = gpu.check_gpu()
    assert result["device"] == "cuda"
    assert result["torch_device_available"] is True
    assert result["install_command"] is None
    assert result["gpu_name"] == "NVIDIA RTX 3080"
    assert result["cuda_version"] == "12.4"


def test_nvidia_torch_cpu_only(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", _fake_nvidia_smi())

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    result = gpu.check_gpu()
    assert result["device"] == "cpu"
    assert result["torch_device_available"] is False
    assert result["install_command"] is not None
    assert "cu124" in result["install_command"]


def test_nvidia_torch_missing(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", _fake_nvidia_smi())

    # Setting a module to None in sys.modules causes import to raise ImportError
    monkeypatch.setitem(sys.modules, "torch", None)

    result = gpu.check_gpu()
    assert result["torch_installed"] is False
    assert result["install_command"] is not None


def test_apple_silicon_mps(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    result = gpu.check_gpu()
    assert result["device"] == "mps"
    assert result["torch_device_available"] is True
    assert result["install_command"] is None


def test_apple_silicon_no_mps(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.1.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    result = gpu.check_gpu()
    assert result["device"] == "cpu"
    assert result["install_command"] is not None
    assert "upgrade" in result["install_command"]


def test_cpu_only_no_gpu(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

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

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    # Should not crash
    result = gpu.check_gpu()
    assert result["device"] == "cpu"


def test_cuda_version_mapping():
    assert gpu._map_cuda_to_wheel("11.8") == "cu118"
    assert gpu._map_cuda_to_wheel("12.1") == "cu121"
    assert gpu._map_cuda_to_wheel("12.3") == "cu121"
    assert gpu._map_cuda_to_wheel("12.4") == "cu124"
    assert gpu._map_cuda_to_wheel("12.6") == "cu124"
    assert gpu._map_cuda_to_wheel("13.0") == "cu124"


def test_windows_nvidia_smi_path(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    monkeypatch.setattr("shutil.which", lambda x: None)

    # Monkeypatch the helpers to simulate Windows detection results
    monkeypatch.setattr(
        gpu, "_run_nvidia_smi_query", lambda: ("NVIDIA RTX 4090", "545.0")
    )
    monkeypatch.setattr(gpu, "_parse_cuda_version", lambda: "12.4")

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    result = gpu.check_gpu()
    assert result["gpu_name"] == "NVIDIA RTX 4090"
    assert result["install_command"] is not None
    assert "cu124" in result["install_command"]


def test_json_output(monkeypatch, capsys):
    """check_gpu.py main() outputs valid JSON."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(subprocess, "run", _nvidia_smi_missing)

    fake_torch = types.ModuleType("torch")
    fake_torch.__version__ = "2.3.0"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    gpu.main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "device" in data
    assert "message" in data
