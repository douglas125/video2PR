"""Regression tests for pinned, recoverable updates."""

import copy
import json
import sys
import urllib.error
from unittest.mock import patch

import pytest
from conftest import import_script

update = import_script("check_update.py")
SHA = "a" * 40


@pytest.fixture
def installation(tmp_path):
    scripts = tmp_path / ".agents/skills/video2pr/scripts"
    scripts.mkdir(parents=True)
    config = {
        "repo": "test/repo",
        "branch": "main",
        "skill_dir": ".agents/skills/video2pr",
        "installed_at": "2020-01-01T00:00:00Z",
        "installed_revision": "b" * 40,
    }
    (scripts.parent / ".video2pr_install.json").write_text(json.dumps(config))
    (scripts.parent / "SKILL.md").write_text("old skill")
    return scripts, config


def serve(monkeypatch, fail=None):
    monkeypatch.setattr(update, "fetch_json", lambda url: {"sha": SHA})

    def fetch(url):
        assert f"/{SHA}/" in url
        if fail and url.endswith(fail):
            raise urllib.error.URLError("network failed")
        if url.endswith("scripts/check_update.py"):
            return "SCRIPT_NAMES = " + repr(update.SCRIPT_NAMES) + "\n"
        if url.endswith("SKILL.md"):
            return "Run scripts/check_deps.py and environment.yml"
        return "# valid payload\n"

    monkeypatch.setattr(update, "fetch_text", fetch)
    return fetch


def test_missing_config_is_optional(tmp_path):
    with pytest.raises(SystemExit) as exc:
        update.load_config(tmp_path)
    assert exc.value.code == 0


def test_legacy_install_requires_refresh(monkeypatch, capsys):
    monkeypatch.setattr(update, "fetch_json", lambda url: {"sha": SHA})
    assert update.check({"repo": "test/repo", "installed_at": "2999-01-01T00:00:00Z"})
    assert "UPDATE_AVAILABLE" in capsys.readouterr().out


def test_same_revision_up_to_date(monkeypatch):
    monkeypatch.setattr(update, "fetch_json", lambda url: {"sha": SHA})
    assert not update.check({"repo": "test/repo", "installed_revision": SHA})


def test_apply_updates_all_payload_and_metadata(installation, monkeypatch):
    scripts, config = installation
    serve(monkeypatch)
    update.apply_update(config, scripts)
    assert config["installed_revision"] == SHA
    assert (scripts.parent / "agents/openai.yaml").is_file()
    assert (
        ".agents/skills/video2pr/scripts/check_deps.py" in (scripts.parent / "SKILL.md").read_text()
    )
    assert json.loads((scripts.parent / ".video2pr_install.json").read_text()) == config
    assert len(config["file_hashes"]) == len(update.SCRIPT_NAMES) + 3


def test_apply_copilot_root_agent(tmp_path, monkeypatch):
    scripts = tmp_path / ".github/skills/video2pr/scripts"
    scripts.mkdir(parents=True)
    config = {"repo": "test/repo", "skill_dir": ".github/skills/video2pr"}
    serve(monkeypatch)
    update.apply_update(config, scripts)
    assert (tmp_path / ".github/agents/video2pr.agent.md").is_file()


@pytest.mark.parametrize("failure", ["transcribe.py", "SKILL.md", "environment.yml", "openai.yaml"])
def test_failed_download_preserves_installation(installation, monkeypatch, failure):
    scripts, config = installation
    before = copy.deepcopy(config)
    serve(monkeypatch, failure)
    with pytest.raises(urllib.error.URLError):
        update.apply_update(config, scripts)
    assert config == before
    assert (scripts.parent / "SKILL.md").read_text() == "old skill"
    assert json.loads((scripts.parent / ".video2pr_install.json").read_text()) == before
    assert not (scripts / "transcribe.py").exists()


def test_replacement_failure_rolls_back(installation, monkeypatch):
    scripts, config = installation
    serve(monkeypatch)
    original_replace = update.os.replace

    def replace(src, dst):
        if str(src).endswith("environment.yml") and ".video2pr-update-" in str(src):
            raise OSError("disk failure")
        return original_replace(src, dst)

    monkeypatch.setattr(update.os, "replace", replace)
    with pytest.raises(OSError, match="disk failure"):
        update.apply_update(config, scripts)
    assert (scripts.parent / "SKILL.md").read_text() == "old skill"
    assert not (scripts / "transcribe.py").exists()
    assert config["installed_revision"] == "b" * 40


def test_payload_unchanged_on_unrelated_commit(installation, monkeypatch):
    scripts, config = installation
    serve(monkeypatch)
    update.apply_update(config, scripts)
    config["installed_revision"] = "c" * 40
    assert not update.check(config)
    config["file_hashes"].pop(".agents/skills/video2pr/agents/openai.yaml")
    assert update.check(config)


def test_new_scripts_are_read_without_executing_manifest():
    content = "SCRIPT_NAMES = ['check_update.py', 'new.py']\nraise RuntimeError('must not run')"
    assert update.remote_script_names(content) == ["check_update.py", "new.py"]
    with pytest.raises(ValueError):
        update.remote_script_names("SCRIPT_NAMES = ['../escape.py']")


def test_invalid_location_rejected(installation):
    scripts, config = installation
    with pytest.raises(ValueError, match="location"):
        update.project_root(scripts, ".github/skills/video2pr")


@pytest.mark.parametrize("apply", [False, True])
def test_cli_network_failure_exit_status(monkeypatch, apply, capsys):
    monkeypatch.setattr(sys, "argv", ["check_update.py"] + (["--apply"] if apply else []))
    monkeypatch.setattr(
        update,
        "load_config",
        lambda _: {"repo": "test/repo", "skill_dir": ".agents/skills/video2pr"},
    )
    with patch.object(update, "fetch_json", side_effect=urllib.error.URLError("offline")):
        if apply:
            # The CLI source location is not an installed skill, also a fatal apply error.
            with pytest.raises(SystemExit) as exc:
                update.main()
            assert exc.value.code == 1
            assert "UPDATE_FAILED" in capsys.readouterr().err
        else:
            update.main()
            assert "CHECK_SKIPPED" in capsys.readouterr().out
