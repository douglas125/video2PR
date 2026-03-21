"""Shared fixtures for video2pr tests."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def import_script(name: str):
    """Import a script by file path, avoiding sys.path pollution."""
    if "/" in name:
        script_path = REPO_ROOT / name
    else:
        script_path = REPO_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        name.replace("/", ".").removesuffix(".py"), script_path
    )
    mod = importlib.util.module_from_spec(spec)
    # Temporarily add to sys.modules so relative imports work
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_install_mod = import_script("./install_video2pr.py")
SCRIPT_NAMES = _install_mod.SCRIPT_NAMES

SKILL_MD_CONTENT = """\
---
name: video2pr
---

Run `python scripts/check_deps.py` first.
Install with `conda env create -f environment.yml`.
"""


@pytest.fixture(scope="session")
def fake_repo(tmp_path_factory):
    """Create a minimal source repo in a temp dir."""
    root = tmp_path_factory.mktemp("fakerepo")

    # scripts/ with stubs
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    for name in SCRIPT_NAMES:
        (scripts_dir / name).write_text("# stub\n")

    # environment.yml
    (root / "environment.yml").write_text("name: video2pr\ndependencies:\n  - python\n")

    # .claude/skills/video2pr/SKILL.md
    claude_skill = root / ".claude" / "skills" / "video2pr"
    claude_skill.mkdir(parents=True)
    (claude_skill / "SKILL.md").write_text(SKILL_MD_CONTENT)

    # .agents/skills/video2pr/SKILL.md + agents/openai.yaml
    agents_skill = root / ".agents" / "skills" / "video2pr"
    agents_skill.mkdir(parents=True)
    (agents_skill / "SKILL.md").write_text(SKILL_MD_CONTENT)
    agents_dir = agents_skill / "agents"
    agents_dir.mkdir()
    (agents_dir / "openai.yaml").write_text("# stub openai.yaml\n")

    # .github/skills/video2pr/SKILL.md
    gh_skill = root / ".github" / "skills" / "video2pr"
    gh_skill.mkdir(parents=True)
    (gh_skill / "SKILL.md").write_text(SKILL_MD_CONTENT)

    # .github/agents/video2pr.agent.md
    gh_agents = root / ".github" / "agents"
    gh_agents.mkdir(parents=True)
    (gh_agents / "video2pr.agent.md").write_text("# stub agent\n")

    return root


@pytest.fixture
def target_dir(tmp_path):
    """Fresh empty directory per test."""
    d = tmp_path / "target"
    d.mkdir()
    return d
