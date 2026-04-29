#!/usr/bin/env python3
"""Render skill/SKILL.md (canonical template) into the three per-platform copies.

Usage:
  python scripts/sync_skill.py            # write the three copies
  python scripts/sync_skill.py --check    # exit 1 if any copy is out of sync
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "skill" / "SKILL.md"

SHARED_DESCRIPTION = (
    "description: >-\n"
    "  Convert a meeting recording into an actionable implementation plan.\n"
    "  Extracts audio, transcribes with timestamps, analyzes the codebase\n"
    "  against what was discussed, and produces a concrete plan of what to\n"
    "  build or change. Argument: path to a video file."
)

CLAUDE_FRONTMATTER = f"""---
name: video2pr
{SHARED_DESCRIPTION}
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - EnterPlanMode
  - ExitPlanMode
---"""

CODEX_FRONTMATTER = f"""---
name: video2pr
{SHARED_DESCRIPTION}
license: MIT
compatibility: "Requires conda, ffmpeg, and Python 3.13+. Install with: conda env create -f environment.yml"
metadata:
  author: douglas125
  version: "1.0"
allowed-tools: shell read_file apply_patch list_dir grep_files
---"""

COPILOT_FRONTMATTER = f"""---
name: video2pr
{SHARED_DESCRIPTION}
license: MIT
compatibility: "Requires conda, ffmpeg, and Python 3.13+. Install with: conda env create -f environment.yml"
metadata:
  author: douglas125
  version: "1.0"
allowed-tools: Bash Read Write Glob
---"""

CLAUDE_TOKENS = {
    "FRONTMATTER": CLAUDE_FRONTMATTER,
    "AGENT_ATTRIBUTION": "by Claude ",
    "CODEBASE_SEARCH_INSTRUCTION": (
        "use Glob and Read to search the codebase **within the repository root**"
        " — not the video file's directory"
    ),
    "STEP_5_6_TITLE": "Enter Plan Mode",
    "STEP_5_6_BODY": (
        "This is the ONLY user approval checkpoint before Phase 6. After writing "
        "`plan.md` and `progress.md`, promptly use `EnterPlanMode` to present the "
        "implementation plan for review — do not add extra interaction or delays "
        "before entering plan mode. Walk through the proposed tasks, highlight the "
        "top priorities, and let the user approve, adjust, or reprioritize. Use "
        "`ExitPlanMode` once the user confirms the plan, then proceed to Phase 6."
    ),
}

GENERIC_TOKENS = {
    "AGENT_ATTRIBUTION": "",
    "CODEBASE_SEARCH_INSTRUCTION": (
        "search the codebase **within the repository root** using file listing and "
        "content search tools — not the video file's directory"
    ),
    "STEP_5_6_TITLE": "Present Plan for Review",
    "STEP_5_6_BODY": (
        "This is the ONLY user approval checkpoint before Phase 6. After writing "
        "`plan.md` and `progress.md`, present the implementation plan for review. "
        "Walk through the proposed tasks, highlight the top priorities, and let "
        "the user approve, adjust, or reprioritize before proceeding to Phase 6."
    ),
}

PLATFORMS = {
    "claude": {
        "out_path": REPO_ROOT / ".claude" / "skills" / "video2pr" / "SKILL.md",
        "tokens": CLAUDE_TOKENS,
    },
    "codex": {
        "out_path": REPO_ROOT / ".agents" / "skills" / "video2pr" / "SKILL.md",
        "tokens": {**GENERIC_TOKENS, "FRONTMATTER": CODEX_FRONTMATTER},
    },
    "copilot": {
        "out_path": REPO_ROOT / ".github" / "skills" / "video2pr" / "SKILL.md",
        "tokens": {**GENERIC_TOKENS, "FRONTMATTER": COPILOT_FRONTMATTER},
    },
}


def render(template: str, tokens: dict) -> str:
    """Substitute {{TOKEN}} placeholders in the template."""
    out = template
    for key, value in tokens.items():
        out = out.replace("{{" + key + "}}", value)
    if "{{" in out:
        unresolved = [line for line in out.splitlines() if "{{" in line][:3]
        raise ValueError(f"Unresolved placeholders after rendering: {unresolved}")
    return out


def render_all() -> dict:
    """Render the template for every platform. Returns name → rendered text."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return {name: render(template, cfg["tokens"]) for name, cfg in PLATFORMS.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if generated files differ from on-disk copies",
    )
    args = parser.parse_args()

    rendered = render_all()
    drift = []

    for name, cfg in PLATFORMS.items():
        out_path = cfg["out_path"]
        new_text = rendered[name]

        if args.check:
            current = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
            if current != new_text:
                drift.append(out_path.relative_to(REPO_ROOT))
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_text, encoding="utf-8")
            print(f"  wrote {out_path.relative_to(REPO_ROOT)}")

    if args.check:
        if drift:
            print("Out of sync (run `python scripts/sync_skill.py`):", file=sys.stderr)
            for p in drift:
                print(f"  {p}", file=sys.stderr)
            sys.exit(1)
        print("All SKILL.md copies are in sync with skill/SKILL.md.")


if __name__ == "__main__":
    main()
