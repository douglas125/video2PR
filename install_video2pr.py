#!/usr/bin/env python3
"""Install video2pr skill into a target project directory.

Each skill folder is fully self-contained: SKILL.md + scripts + environment.yml.
No files are placed at the target project root (except .github/agents/ for Copilot).
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Source repo root (where this script lives)
REPO_ROOT = Path(__file__).resolve().parent

SCRIPT_NAMES = [
    "check_deps.py",
    "check_update.py",
    "convert_transcript.py",
    "extract_audio.py",
    "extract_frame.py",
    "get_duration.py",
    "transcribe.py",
]

ASSISTANTS = {
    "claude-code": {
        "skill_dir": ".claude/skills/video2pr",
        "skill_md": ".claude/skills/video2pr/SKILL.md",
        "extra_files": [],
    },
    "codex": {
        "skill_dir": ".agents/skills/video2pr",
        "skill_md": ".agents/skills/video2pr/SKILL.md",
        "extra_files": [
            # (source_relative, dest_relative_to_skill_dir)
            (".agents/skills/video2pr/agents/openai.yaml", "agents/openai.yaml"),
        ],
    },
    "copilot": {
        "skill_dir": ".github/skills/video2pr",
        "skill_md": ".github/skills/video2pr/SKILL.md",
        "extra_files": [
            # This one goes outside the skill dir — handled specially
        ],
        "root_files": [
            (".github/agents/video2pr.agent.md", ".github/agents/video2pr.agent.md"),
        ],
    },
}


def rewrite_paths(content: str, skill_dir: str) -> str:
    """Rewrite script and environment paths in SKILL.md to use the skill directory prefix."""
    content = content.replace("scripts/", f"{skill_dir}/scripts/")
    content = content.replace("environment.yml", f"{skill_dir}/environment.yml")
    return content


def check_source_files() -> list[str]:
    """Verify all required source files exist. Returns list of errors."""
    errors = []
    for name in SCRIPT_NAMES:
        if not (REPO_ROOT / "scripts" / name).exists():
            errors.append(f"Missing script: scripts/{name}")
    if not (REPO_ROOT / "environment.yml").exists():
        errors.append("Missing: environment.yml")
    for assistant, cfg in ASSISTANTS.items():
        skill_md = REPO_ROOT / cfg["skill_md"]
        if not skill_md.exists():
            errors.append(f"Missing: {cfg['skill_md']}")
    return errors


def get_conflicts(target: Path, assistants: list[str]) -> list[str]:
    """Check for existing skill folders at the target."""
    conflicts = []
    for name in assistants:
        cfg = ASSISTANTS[name]
        skill_path = target / cfg["skill_dir"]
        if skill_path.exists():
            conflicts.append(str(skill_path))
    return conflicts


def install_assistant(target: Path, name: str, dry_run: bool) -> list[str]:
    """Install one assistant's skill folder. Returns list of installed paths."""
    cfg = ASSISTANTS[name]
    skill_dir = cfg["skill_dir"]
    dest = target / skill_dir
    installed = []

    # Create scripts directory
    scripts_dest = dest / "scripts"
    if dry_run:
        print(f"  mkdir -p {scripts_dest.relative_to(target)}")
    else:
        scripts_dest.mkdir(parents=True, exist_ok=True)

    # Copy scripts
    for script_name in SCRIPT_NAMES:
        src = REPO_ROOT / "scripts" / script_name
        dst = scripts_dest / script_name
        if dry_run:
            print(f"  copy scripts/{script_name} -> {dst.relative_to(target)}")
        else:
            shutil.copy2(src, dst)
        installed.append(f"scripts/{script_name}")

    # Copy environment.yml
    src = REPO_ROOT / "environment.yml"
    dst = dest / "environment.yml"
    if dry_run:
        print(f"  copy environment.yml -> {dst.relative_to(target)}")
    else:
        shutil.copy2(src, dst)
    installed.append("environment.yml")

    # Copy and rewrite SKILL.md
    src = REPO_ROOT / cfg["skill_md"]
    dst = dest / "SKILL.md"
    content = src.read_text()
    content = rewrite_paths(content, skill_dir)
    if dry_run:
        print(f"  copy+rewrite {cfg['skill_md']} -> {dst.relative_to(target)}")
    else:
        dst.write_text(content)
    installed.append("SKILL.md")

    # Copy extra files within skill dir (e.g., openai.yaml)
    for src_rel, dst_rel in cfg.get("extra_files", []):
        src = REPO_ROOT / src_rel
        dst = dest / dst_rel
        if dry_run:
            print(f"  copy {src_rel} -> {dst.relative_to(target)}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        installed.append(dst_rel)

    # Copy root-level files (e.g., copilot agent.md)
    for src_rel, dst_rel in cfg.get("root_files", []):
        src = REPO_ROOT / src_rel
        dst = target / dst_rel
        if dry_run:
            print(f"  copy {src_rel} -> {dst.relative_to(target)}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        installed.append(dst_rel)

    # Write install config
    config = {
        "repo": "douglas125/video2PR",
        "branch": "main",
        "skill_dir": skill_dir,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assistants_installed": [name],
    }
    config_path = dest / ".video2pr_install.json"
    if dry_run:
        print(f"  write {config_path.relative_to(target)}")
    else:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
    installed.append(".video2pr_install.json")

    return installed


def main():
    parser = argparse.ArgumentParser(
        description="Install video2pr skill into a target project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python install_video2pr.py /path/to/project\n"
            "  python install_video2pr.py /path/to/project --assistants claude-code\n"
            "  python install_video2pr.py /path/to/project --dry-run\n"
        ),
    )
    parser.add_argument("target_path", type=Path,
                        help="Target project root directory")
    parser.add_argument("--assistants", nargs="+",
                        choices=["claude-code", "codex", "copilot"],
                        default=["claude-code", "codex", "copilot"],
                        help="Which assistants to install for (default: all)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing skill folders")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be installed without writing")
    args = parser.parse_args()

    target = args.target_path.resolve()

    # Validate target
    if not target.exists() or not target.is_dir():
        print(f"Error: {target} does not exist or is not a directory.", file=sys.stderr)
        sys.exit(1)

    # Validate source files
    errors = check_source_files()
    if errors:
        print("Error: Source files missing. Are you running from the video2PR repo?",
              file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    # Check for conflicts
    if not args.force and not args.dry_run:
        conflicts = get_conflicts(target, args.assistants)
        if conflicts:
            print("Error: Existing skill folders found (use --force to overwrite):",
                  file=sys.stderr)
            for c in conflicts:
                print(f"  {c}", file=sys.stderr)
            sys.exit(1)

    # Remove existing skill folders if --force
    if args.force and not args.dry_run:
        for name in args.assistants:
            cfg = ASSISTANTS[name]
            skill_path = target / cfg["skill_dir"]
            if skill_path.exists():
                shutil.rmtree(skill_path)

    # Install
    if args.dry_run:
        print(f"Dry run — would install to {target}\n")

    summary_lines = []
    for name in args.assistants:
        cfg = ASSISTANTS[name]
        if args.dry_run:
            print(f"[{name}] -> {cfg['skill_dir']}/")
        installed = install_assistant(target, name, args.dry_run)
        if args.dry_run:
            print()

        # Build summary
        script_count = sum(1 for i in installed if i.startswith("scripts/"))
        extras = []
        if any("openai.yaml" in i for i in installed):
            extras.append("agents/openai.yaml")
        parts = f"SKILL.md + environment.yml + {script_count} scripts"
        if extras:
            parts += " + " + " + ".join(extras)
        label = f"{name}:".ljust(13)
        summary_lines.append(f"  {label}{cfg['skill_dir']}/ ({parts})")

        # Copilot root file
        if name == "copilot":
            summary_lines.append(
                f"  {'':13}.github/agents/video2pr.agent.md"
            )

    if not args.dry_run:
        # Determine which env path to show (use first assistant's)
        first_cfg = ASSISTANTS[args.assistants[0]]
        env_path = f"{first_cfg['skill_dir']}/environment.yml"

        print(f"\nvideo2pr installed to {target}\n")
        for line in summary_lines:
            print(line)
        print(f"\n  Next steps:")
        print(f"    1. conda env create -f {env_path}")
        print(f"    2. Use /video2pr <video-path> in your coding assistant")


if __name__ == "__main__":
    main()
