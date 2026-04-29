"""Tests for scripts/sync_skill.py."""

import sys

import pytest
from conftest import import_script

sync_skill = import_script("sync_skill.py")


def test_render_substitutes_all_tokens():
    template = "{{FRONTMATTER}}\n\n{{AGENT_ATTRIBUTION}}done."
    out = sync_skill.render(
        template,
        {"FRONTMATTER": "---\nname: x\n---", "AGENT_ATTRIBUTION": "by Claude "},
    )
    assert out == "---\nname: x\n---\n\nby Claude done."


def test_render_raises_on_unresolved_token():
    with pytest.raises(ValueError, match="Unresolved placeholders"):
        sync_skill.render("{{MISSING}}", {})


def test_claude_render_contains_plan_mode_terms():
    rendered = sync_skill.render_all()
    claude = rendered["claude"]
    assert "EnterPlanMode" in claude
    assert "ExitPlanMode" in claude
    assert "by Claude directly" in claude
    assert "Glob and Read" in claude


def test_codex_render_strips_claude_specifics():
    rendered = sync_skill.render_all()
    codex = rendered["codex"]
    assert "EnterPlanMode" not in codex
    assert "ExitPlanMode" not in codex
    assert "by Claude" not in codex
    assert "shell read_file apply_patch list_dir grep_files" in codex
    assert "file listing and content search tools" in codex


def test_copilot_render_uses_copilot_tools():
    rendered = sync_skill.render_all()
    copilot = rendered["copilot"]
    assert "EnterPlanMode" not in copilot
    assert "allowed-tools: Bash Read Write Glob" in copilot


def test_check_mode_passes_when_in_sync():
    """The committed copies should match the rendered template."""
    import contextlib
    import io

    saved_argv = sys.argv
    sys.argv = ["sync_skill.py", "--check"]
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync_skill.main()
        assert "in sync" in buf.getvalue()
    finally:
        sys.argv = saved_argv


def test_all_three_outputs_have_distinct_frontmatter():
    rendered = sync_skill.render_all()
    fronts = {name: out.split("---\n", 2)[1] for name, out in rendered.items()}
    assert len({fronts["claude"], fronts["codex"], fronts["copilot"]}) == 3
