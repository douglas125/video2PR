#!/usr/bin/env python3
"""Check for and apply video2pr updates from GitHub."""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/{repo}/commits"
GITHUB_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

SCRIPT_NAMES = [
    "check_deps.py",
    "check_update.py",
    "convert_transcript.py",
    "extract_audio.py",
    "extract_frame.py",
    "get_duration.py",
    "transcribe.py",
]

# Map assistant key to the source SKILL.md path in the repo
SKILL_MD_SOURCES = {
    ".claude/skills/video2pr": ".claude/skills/video2pr/SKILL.md",
    ".agents/skills/video2pr": ".agents/skills/video2pr/SKILL.md",
    ".github/skills/video2pr": ".github/skills/video2pr/SKILL.md",
}


def load_config(script_dir: Path) -> dict:
    """Load .video2pr_install.json from the skill directory (parent of scripts/)."""
    config_path = script_dir.parent / ".video2pr_install.json"
    if not config_path.exists():
        print("CHECK_SKIPPED: No .video2pr_install.json found", file=sys.stderr)
        sys.exit(0)
    with open(config_path) as f:
        return json.load(f)


def fetch_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "video2pr-updater"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def fetch_text(url: str) -> str:
    """Fetch text content from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "video2pr-updater"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode()


def check(config: dict) -> bool:
    """Check if updates are available. Returns True if update available."""
    repo = config["repo"]
    branch = config.get("branch", "main")
    installed_at = config["installed_at"]

    url = GITHUB_API.format(repo=repo) + f"?path=scripts&sha={branch}&per_page=1"
    commits = fetch_json(url)

    if not commits:
        print("UP_TO_DATE")
        return False

    latest_date = commits[0]["commit"]["committer"]["date"]
    if latest_date <= installed_at:
        print("UP_TO_DATE")
        return False

    print(f"UPDATE_AVAILABLE: New changes since {installed_at}. "
          f"Run with --apply to update.")
    return True


def rewrite_paths(content: str, skill_dir: str) -> str:
    """Rewrite script and environment paths in SKILL.md content."""
    content = content.replace("scripts/", f"{skill_dir}/scripts/")
    content = content.replace("environment.yml", f"{skill_dir}/environment.yml")
    return content


def apply_update(config: dict, script_dir: Path) -> None:
    """Download and apply updates."""
    repo = config["repo"]
    branch = config.get("branch", "main")
    skill_dir = config["skill_dir"]
    base_dir = script_dir.parent  # the skill directory

    updated = []

    # Update scripts
    for name in SCRIPT_NAMES:
        url = GITHUB_RAW.format(repo=repo, branch=branch, path=f"scripts/{name}")
        try:
            content = fetch_text(url)
            dest = script_dir / name
            dest.write_text(content)
            updated.append(f"scripts/{name}")
        except urllib.error.HTTPError as e:
            print(f"  Warning: could not download {name}: {e}", file=sys.stderr)

    # Update environment.yml
    url = GITHUB_RAW.format(repo=repo, branch=branch, path="environment.yml")
    try:
        content = fetch_text(url)
        (base_dir / "environment.yml").write_text(content)
        updated.append("environment.yml")
    except urllib.error.HTTPError as e:
        print(f"  Warning: could not download environment.yml: {e}", file=sys.stderr)

    # Update SKILL.md with path rewriting
    source_path = SKILL_MD_SOURCES.get(skill_dir)
    if source_path:
        url = GITHUB_RAW.format(repo=repo, branch=branch, path=source_path)
        try:
            content = fetch_text(url)
            content = rewrite_paths(content, skill_dir)
            (base_dir / "SKILL.md").write_text(content)
            updated.append("SKILL.md")
        except urllib.error.HTTPError as e:
            print(f"  Warning: could not download SKILL.md: {e}", file=sys.stderr)

    # Update installed_at in config
    config["installed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    config_path = base_dir / ".video2pr_install.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    if updated:
        print(f"UPDATED: {', '.join(updated)}")
    else:
        print("No files were updated.")


def main():
    parser = argparse.ArgumentParser(description="Check for video2pr updates")
    parser.add_argument("--apply", action="store_true",
                        help="Download and apply available updates")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    config = load_config(script_dir)

    try:
        if args.apply:
            apply_update(config, script_dir)
        else:
            check(config)
    except (urllib.error.URLError, OSError) as e:
        print(f"CHECK_SKIPPED: {e}")


if __name__ == "__main__":
    main()
