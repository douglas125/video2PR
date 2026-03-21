"""Tests for scripts/check_update.py."""

import json
import sys
import urllib.error

import pytest

from conftest import import_script

check_update = import_script("check_update.py")


# ── Config loading ──────────────────────────────────────────────────


def test_load_config_missing(tmp_path):
    """No config file → SystemExit(0), stderr has CHECK_SKIPPED."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    with pytest.raises(SystemExit, match="0"):
        check_update.load_config(scripts_dir)


def test_load_config_valid(tmp_path):
    """Write JSON to tmp_path, assert dict returned correctly."""
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    config = {"repo": "test/repo", "installed_at": "2025-01-01T00:00:00Z"}
    (skill_dir / ".video2pr_install.json").write_text(json.dumps(config))
    result = check_update.load_config(scripts_dir)
    assert result["repo"] == "test/repo"


# ── Check mode ──────────────────────────────────────────────────────


def test_check_up_to_date(monkeypatch, capsys):
    """Commit date older than installed_at → UP_TO_DATE."""
    config = {
        "repo": "test/repo",
        "branch": "main",
        "installed_at": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr(
        check_update,
        "fetch_json",
        lambda url: [{"commit": {"committer": {"date": "2025-06-01T00:00:00Z"}}}],
    )
    result = check_update.check(config)
    assert result is False
    assert "UP_TO_DATE" in capsys.readouterr().out


def test_check_update_available(monkeypatch, capsys):
    """Commit date newer → UPDATE_AVAILABLE."""
    config = {
        "repo": "test/repo",
        "branch": "main",
        "installed_at": "2025-01-01T00:00:00Z",
    }
    monkeypatch.setattr(
        check_update,
        "fetch_json",
        lambda url: [{"commit": {"committer": {"date": "2025-06-01T00:00:00Z"}}}],
    )
    result = check_update.check(config)
    assert result is True
    assert "UPDATE_AVAILABLE" in capsys.readouterr().out


def test_check_no_commits(monkeypatch, capsys):
    """Empty commit list → UP_TO_DATE."""
    config = {
        "repo": "test/repo",
        "branch": "main",
        "installed_at": "2025-01-01T00:00:00Z",
    }
    monkeypatch.setattr(check_update, "fetch_json", lambda url: [])
    result = check_update.check(config)
    assert result is False
    assert "UP_TO_DATE" in capsys.readouterr().out


def test_check_skill_md_update_detected(monkeypatch, capsys):
    """Update in SKILL.md (not scripts/) is detected."""
    config = {
        "repo": "test/repo",
        "branch": "main",
        "installed_at": "2025-06-01T00:00:00Z",
        "skill_dir": ".claude/skills/video2pr",
    }

    def mock_fetch_json(url):
        if "path=scripts" in url or "path=environment.yml" in url:
            # scripts and environment.yml are old
            return [{"commit": {"committer": {"date": "2025-01-01T00:00:00Z"}}}]
        if "SKILL.md" in url:
            # SKILL.md has a newer commit
            return [{"commit": {"committer": {"date": "2025-12-01T00:00:00Z"}}}]
        return []

    monkeypatch.setattr(check_update, "fetch_json", mock_fetch_json)
    result = check_update.check(config)
    assert result is True
    assert "UPDATE_AVAILABLE" in capsys.readouterr().out


# ── Apply mode ──────────────────────────────────────────────────────


def test_apply_downloads_and_rewrites(tmp_path, monkeypatch, capsys):
    """Set up fake skill dir, mock downloads, verify files and rewriting."""
    skill_dir = tmp_path / ".claude" / "skills" / "video2pr"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    config = {
        "repo": "test/repo",
        "branch": "main",
        "skill_dir": ".claude/skills/video2pr",
        "installed_at": "2025-01-01T00:00:00Z",
    }
    (skill_dir / ".video2pr_install.json").write_text(json.dumps(config))
    (skill_dir / "SKILL.md").write_text("old content")

    def mock_fetch_text(url):
        if "SKILL.md" in url:
            return "Run scripts/check_deps.py and environment.yml"
        return f"# content for {url.split('/')[-1]}"

    monkeypatch.setattr(check_update, "fetch_text", mock_fetch_text)
    check_update.apply_update(config, scripts_dir)

    # SKILL.md should have rewritten paths
    skill_md = (skill_dir / "SKILL.md").read_text()
    assert ".claude/skills/video2pr/scripts/" in skill_md
    assert ".claude/skills/video2pr/environment.yml" in skill_md

    # installed_at should be updated
    new_config = json.loads((skill_dir / ".video2pr_install.json").read_text())
    assert new_config["installed_at"] > "2025-01-01T00:00:00Z"

    assert "UPDATED" in capsys.readouterr().out


def test_apply_handles_http_error(tmp_path, monkeypatch, capsys):
    """One download raises HTTPError, others succeed, no crash."""
    skill_dir = tmp_path / ".claude" / "skills" / "video2pr"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)

    config = {
        "repo": "test/repo",
        "branch": "main",
        "skill_dir": ".claude/skills/video2pr",
        "installed_at": "2025-01-01T00:00:00Z",
    }
    (skill_dir / ".video2pr_install.json").write_text(json.dumps(config))

    call_count = 0

    def mock_fetch_text(url):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return "# content"

    monkeypatch.setattr(check_update, "fetch_text", mock_fetch_text)
    # Should not raise
    check_update.apply_update(config, scripts_dir)


# ── Network error ───────────────────────────────────────────────────


def test_main_network_error(tmp_path, monkeypatch, capsys):
    """URLError → stdout CHECK_SKIPPED."""
    # Set up config so load_config succeeds
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    config = {
        "repo": "test/repo",
        "branch": "main",
        "installed_at": "2025-01-01T00:00:00Z",
    }
    (skill_dir / ".video2pr_install.json").write_text(json.dumps(config))

    monkeypatch.setattr(sys, "argv", ["check_update.py"])
    monkeypatch.setattr(
        check_update, "load_config", lambda _: config
    )
    def raise_url_error(url):
        raise urllib.error.URLError("Network down")

    monkeypatch.setattr(check_update, "fetch_json", raise_url_error)
    check_update.main()
    assert "CHECK_SKIPPED" in capsys.readouterr().out
