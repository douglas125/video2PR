"""Tests for install_video2pr.py."""

import json
import sys

import pytest

from conftest import import_script

install = import_script("./install_video2pr.py")


# ── Pure functions ──────────────────────────────────────────────────


def test_rewrite_paths_scripts():
    result = install.rewrite_paths(
        "python scripts/check_deps.py", ".claude/skills/video2pr"
    )
    assert result == "python .claude/skills/video2pr/scripts/check_deps.py"


def test_rewrite_paths_environment():
    result = install.rewrite_paths(
        "conda env create -f environment.yml", ".claude/skills/video2pr"
    )
    assert "conda env create -f .claude/skills/video2pr/environment.yml" == result


def test_rewrite_paths_no_match():
    text = "nothing to rewrite here"
    assert install.rewrite_paths(text, ".claude/skills/video2pr") == text


def test_rewrite_paths_codex():
    result = install.rewrite_paths(
        "python scripts/check_deps.py\nconda env create -f environment.yml",
        ".agents/skills/video2pr",
    )
    assert "python .agents/skills/video2pr/scripts/check_deps.py" in result
    assert "conda env create -f .agents/skills/video2pr/environment.yml" in result


def test_rewrite_paths_copilot():
    result = install.rewrite_paths(
        "python scripts/check_deps.py\nconda env create -f environment.yml",
        ".github/skills/video2pr",
    )
    assert "python .github/skills/video2pr/scripts/check_deps.py" in result
    assert "conda env create -f .github/skills/video2pr/environment.yml" in result


# ── Source validation ───────────────────────────────────────────────


def test_check_source_files_all_present(fake_repo, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    assert install.check_source_files() == []


def test_check_source_files_missing_script(tmp_path, monkeypatch):
    # Use an isolated repo to avoid mutating the session-scoped fake_repo
    from conftest import SCRIPT_NAMES, SKILL_MD_CONTENT

    root = tmp_path / "repo"
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True)
    for name in SCRIPT_NAMES:
        if name != "check_deps.py":
            (scripts_dir / name).write_text("# stub\n")
    (root / "environment.yml").write_text("name: video2pr\n")
    for skill_path in [
        ".claude/skills/video2pr",
        ".agents/skills/video2pr",
        ".github/skills/video2pr",
    ]:
        d = root / skill_path
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL_MD_CONTENT)

    monkeypatch.setattr(install, "REPO_ROOT", root)
    errors = install.check_source_files()
    assert any("check_deps.py" in e for e in errors)


# ── Conflict detection ──────────────────────────────────────────────


def test_get_conflicts_empty_target(target_dir):
    assert install.get_conflicts(target_dir, ["claude-code"]) == []


def test_get_conflicts_existing_dir(target_dir):
    (target_dir / ".claude" / "skills" / "video2pr").mkdir(parents=True)
    conflicts = install.get_conflicts(target_dir, ["claude-code"])
    assert len(conflicts) == 1
    assert "video2pr" in conflicts[0]


# ── Single assistant install ────────────────────────────────────────


def test_install_claude_code(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    installed = install.install_assistant(target_dir, "claude-code", dry_run=False)

    skill_dir = target_dir / ".claude" / "skills" / "video2pr"
    # 8 scripts + env + SKILL.md + config
    assert len(installed) == 11
    assert (skill_dir / "scripts" / "transcribe.py").exists()
    assert (skill_dir / "environment.yml").exists()

    # SKILL.md should be rewritten
    skill_md = (skill_dir / "SKILL.md").read_text()
    assert ".claude/skills/video2pr/scripts/" in skill_md
    assert ".claude/skills/video2pr/environment.yml" in skill_md

    # Config JSON
    config_path = skill_dir / ".video2pr_install.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["repo"] == "douglas125/video2PR"
    assert config["skill_dir"] == ".claude/skills/video2pr"


def test_install_codex_has_openai_yaml(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    install.install_assistant(target_dir, "codex", dry_run=False)
    skill_dir = target_dir / ".agents" / "skills" / "video2pr"
    assert (skill_dir / "agents" / "openai.yaml").exists()
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert ".agents/skills/video2pr/scripts/" in skill_md
    assert ".agents/skills/video2pr/environment.yml" in skill_md


def test_install_copilot_has_agent_md(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    install.install_assistant(target_dir, "copilot", dry_run=False)
    skill_dir = target_dir / ".github" / "skills" / "video2pr"
    assert (target_dir / ".github" / "agents" / "video2pr.agent.md").exists()
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert ".github/skills/video2pr/scripts/" in skill_md
    assert ".github/skills/video2pr/environment.yml" in skill_md


def test_install_preserves_utf8_skill_text(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    skill_src = fake_repo / ".agents" / "skills" / "video2pr" / "SKILL.md"
    skill_src.write_text(
        "---\nname: video2pr\n---\n\nPortuguês: negócio e migração.\n",
        encoding="utf-8",
    )

    install.install_assistant(target_dir, "codex", dry_run=False)

    installed = (
        target_dir / ".agents" / "skills" / "video2pr" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "Português: negócio e migração." in installed


# ── Dry run ─────────────────────────────────────────────────────────


def test_dry_run_creates_no_files(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    install.install_assistant(target_dir, "claude-code", dry_run=True)
    # target_dir should still be empty (no child dirs)
    assert list(target_dir.iterdir()) == []


# ── CLI integration ─────────────────────────────────────────────────


def test_main_nonexistent_target(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["install_video2pr.py", "/no/such/path"])
    with pytest.raises(SystemExit, match="1"):
        install.main()


def test_main_conflict_without_force(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    (target_dir / ".claude" / "skills" / "video2pr").mkdir(parents=True)
    monkeypatch.setattr(
        sys, "argv", ["install_video2pr.py", str(target_dir)]
    )
    with pytest.raises(SystemExit, match="1"):
        install.main()


def test_main_force_overwrites(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    # Pre-create a stale file
    skill_dir = target_dir / ".claude" / "skills" / "video2pr"
    skill_dir.mkdir(parents=True)
    (skill_dir / "stale.txt").write_text("old")

    monkeypatch.setattr(
        sys,
        "argv",
        ["install_video2pr.py", str(target_dir), "--force"],
    )
    install.main()

    # Stale file should be gone, fresh install present
    assert not (skill_dir / "stale.txt").exists()
    assert (skill_dir / "SKILL.md").exists()


def test_main_all_three_assistants(fake_repo, target_dir, monkeypatch):
    monkeypatch.setattr(install, "REPO_ROOT", fake_repo)
    monkeypatch.setattr(
        sys,
        "argv",
        ["install_video2pr.py", str(target_dir)],
    )
    install.main()

    assert (target_dir / ".claude" / "skills" / "video2pr" / "SKILL.md").exists()
    assert (target_dir / ".agents" / "skills" / "video2pr" / "SKILL.md").exists()
    assert (target_dir / ".github" / "skills" / "video2pr" / "SKILL.md").exists()
    assert (target_dir / ".github" / "agents" / "video2pr.agent.md").exists()
