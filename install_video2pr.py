#!/usr/bin/env python3
"""Install video2pr skill into a target project directory.

Each skill folder is fully self-contained: SKILL.md + scripts + environment.yml.
No files are placed at the target project root (except .github/agents/ for Copilot).
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scripts.check_update import ASSISTANTS, payload_files, replace_paths, rewrite_paths
from scripts.check_update import SCRIPT_NAMES as SCRIPT_NAMES

REPO_ROOT = Path(__file__).resolve().parent


def check_source_files(assistants=None) -> list[str]:
    """Validate the complete payload of selected assistants."""
    sources = {
        src
        for name in (assistants or ASSISTANTS)
        for src, _ in payload_files(ASSISTANTS[name]["skill_dir"])
    }
    return [f"Missing: {src}" for src in sorted(sources) if not (REPO_ROOT / src).is_file()]


def get_conflicts(target: Path, assistants: list[str]) -> list[str]:
    paths = []
    for name in assistants:
        cfg = ASSISTANTS[name]
        paths.append(target / cfg["skill_dir"])
        paths.extend(target / dst for _, dst in cfg["root_files"])
    return [str(p) for p in paths if p.exists()]


def source_revision() -> str | None:
    """Only stamp clean Git checkouts; archives and modified trees are unknown."""
    try:
        status = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        if status.stdout.strip():
            return None
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def install_assistant(target: Path, name: str, dry_run: bool) -> list[str]:
    """Install one assistant using the same transaction as the multi-assistant CLI."""
    return install_all(target, [name], dry_run)[name]


def install_all(target: Path, names: list[str], dry_run: bool) -> dict[str, list[str]]:
    """Stage every selected assistant before replacing any existing installation."""
    target = target.resolve()
    payload = [
        (name, src, dst)
        for name in names
        for src, dst in payload_files(ASSISTANTS[name]["skill_dir"])
    ]
    for _, src, dst in payload:
        destination = target / dst
        source = (REPO_ROOT / src).resolve()
        if not destination.resolve().is_relative_to(target):
            raise ValueError(f"Destination escapes project: {destination}")
        if destination.resolve() == source:
            raise ValueError("Source and destination overlap; install into another project")
    installed = {name: [] for name in names}
    if dry_run:
        for name, src, dst in payload:
            print(f"  copy {src} -> {dst}")
            installed[name].append(dst.removeprefix(ASSISTANTS[name]["skill_dir"] + "/"))
        return installed
    revision = source_revision()
    with tempfile.TemporaryDirectory(prefix=".video2pr-install-", dir=target) as tmp:
        stage = Path(tmp)
        replacements = []
        for name in names:
            cfg = ASSISTANTS[name]
            skill_dir = cfg["skill_dir"]
            hashes = {}
            for _, src, dst in (entry for entry in payload if entry[0] == name):
                staged = stage / dst
                staged.parent.mkdir(parents=True, exist_ok=True)
                if src == cfg["skill_md"]:
                    staged.write_bytes(
                        rewrite_paths(
                            (REPO_ROOT / src).read_text(encoding="utf-8"), skill_dir
                        ).encode("utf-8")
                    )
                else:
                    shutil.copy2(REPO_ROOT / src, staged)
                hashes[dst] = hashlib.sha256(staged.read_bytes()).hexdigest()
                installed[name].append(dst.removeprefix(skill_dir + "/"))
            config = {
                "repo": "douglas125/video2PR",
                "branch": "main",
                "skill_dir": skill_dir,
                "installed_revision": revision,
                "file_hashes": hashes,
                "installed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "assistants_installed": [name],
            }
            (stage / skill_dir / ".video2pr_install.json").write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )
            installed[name].append(".video2pr_install.json")
            replacements.append((stage / skill_dir, target / skill_dir))
            replacements.extend((stage / dst, target / dst) for _, dst in cfg["root_files"])
        replace_paths(replacements)
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
    parser.add_argument("target_path", type=Path, help="Target project root directory")
    parser.add_argument(
        "--assistants",
        nargs="+",
        choices=["claude-code", "codex", "copilot"],
        default=["claude-code", "codex", "copilot"],
        help="Which assistants to install for (default: all)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing skill folders")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be installed without writing"
    )
    args = parser.parse_args()

    target = args.target_path.resolve()

    # Validate target
    if not target.exists() or not target.is_dir():
        print(f"Error: {target} does not exist or is not a directory.", file=sys.stderr)
        sys.exit(1)

    args.assistants = list(dict.fromkeys(args.assistants))

    # Validate source files
    errors = check_source_files(args.assistants)
    if errors:
        print(
            "Error: Source files missing. Are you running from the video2PR repo?", file=sys.stderr
        )
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    # Check for conflicts
    if not args.force and not args.dry_run:
        conflicts = get_conflicts(target, args.assistants)
        if conflicts:
            print(
                "Error: Existing skill folders found (use --force to overwrite):", file=sys.stderr
            )
            for c in conflicts:
                print(f"  {c}", file=sys.stderr)
            sys.exit(1)

    try:
        all_installed = install_all(target, args.assistants, args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    summary_lines = []
    for name in args.assistants:
        cfg = ASSISTANTS[name]
        if args.dry_run:
            print(f"[{name}] -> {cfg['skill_dir']}/")
        installed = all_installed[name]
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
            summary_lines.append(f"  {'':13}.github/agents/video2pr.agent.md")

    if not args.dry_run:
        # Determine which env path to show (use first assistant's)
        first_cfg = ASSISTANTS[args.assistants[0]]
        env_path = f"{first_cfg['skill_dir']}/environment.yml"

        print(f"\nvideo2pr installed to {target}\n")
        for line in summary_lines:
            print(line)
        print("\n  Next steps:")
        print(f"    1. conda env create -f {env_path}")
        print("    2. Use /video2pr <video-path> in your coding assistant")


if __name__ == "__main__":
    main()
