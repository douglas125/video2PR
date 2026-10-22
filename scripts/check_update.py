#!/usr/bin/env python3
"""Check for and apply video2pr updates from GitHub."""

import argparse
import ast
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/{repo}/commits"
GITHUB_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

SCRIPT_NAMES = [
    "artifacts.py",
    "check_deps.py",
    "check_gpu.py",
    "check_update.py",
    "convert_transcript.py",
    "diagnostics.py",
    "extract_audio.py",
    "extract_frame.py",
    "get_duration.py",
    "transcribe.py",
]

# Kept in this self-contained updater so legacy installations can bootstrap it.
ASSISTANTS = {
    "claude-code": {"skill_dir": ".claude/skills/video2pr", "extra_files": [], "root_files": []},
    "codex": {
        "skill_dir": ".agents/skills/video2pr",
        "extra_files": [(".agents/skills/video2pr/agents/openai.yaml", "agents/openai.yaml")],
        "root_files": [],
    },
    "copilot": {
        "skill_dir": ".github/skills/video2pr",
        "extra_files": [],
        "root_files": [(".github/agents/video2pr.agent.md", ".github/agents/video2pr.agent.md")],
    },
}
for _cfg in ASSISTANTS.values():
    _cfg["skill_md"] = _cfg["skill_dir"] + "/SKILL.md"
SKILL_MD_SOURCES = {cfg["skill_dir"]: cfg["skill_md"] for cfg in ASSISTANTS.values()}


def payload_files(skill_dir: str, script_names=None) -> list[tuple[str, str]]:
    """Return (repository source, project-relative destination) for an assistant."""
    cfg = next((c for c in ASSISTANTS.values() if c["skill_dir"] == skill_dir), None)
    if cfg is None:
        raise ValueError(f"Unknown skill directory: {skill_dir}")
    files = [
        (f"scripts/{n}", f"{skill_dir}/scripts/{n}")
        for n in (SCRIPT_NAMES if script_names is None else script_names)
    ]
    files += [
        ("environment.yml", f"{skill_dir}/environment.yml"),
        (cfg["skill_md"], f"{skill_dir}/SKILL.md"),
    ]
    files += [(src, f"{skill_dir}/{dst}") for src, dst in cfg["extra_files"]]
    return files + cfg["root_files"]


def replace_paths(replacements: list[tuple[Path, Path]]) -> None:
    """Commit staged files/directories, restoring all old paths on an I/O failure.

    Stages must live on the destination filesystem. The metadata entry should
    be last: a process interruption then leaves the previous revision recorded.
    Backups survive if rollback itself fails, for manual recovery.
    """
    committed = []
    backups = []
    try:
        for staged, dest in replacements:
            dest.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if dest.exists():
                backup = dest.with_name(dest.name + ".video2pr-backup-" + uuid.uuid4().hex)
                os.replace(dest, backup)
            backups.append((dest, backup))
            os.replace(staged, dest)
            committed.append(dest)
    except BaseException:
        for dest in reversed(committed):
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        for dest, backup in reversed(backups):
            if backup is not None:
                os.replace(backup, dest)
        raise
    for _, backup in backups:
        if backup is not None:
            try:
                if backup.is_dir():
                    shutil.rmtree(backup)
                else:
                    backup.unlink()
            except OSError as exc:
                print(
                    f"Warning: replacement succeeded; retained backup {backup}: {exc}",
                    file=sys.stderr,
                )


def project_root(script_dir: Path, skill_dir: str) -> Path:
    base = script_dir.resolve().parent
    parts = Path(skill_dir).parts
    if tuple(base.parts[-len(parts) :]) != parts:
        raise ValueError("Install configuration does not match the updater location")
    root = base
    for _ in parts:
        root = root.parent
    return root


def remote_revision(config: dict) -> str:
    branch = urllib.parse.quote(config.get("branch", "main"), safe="")
    payload = fetch_json(GITHUB_API.format(repo=config["repo"]) + f"/{branch}")
    revision = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("GitHub returned an invalid commit revision")
    return revision


def load_config(script_dir: Path) -> dict:
    """Load .video2pr_install.json from the skill directory (parent of scripts/)."""
    config_path = script_dir.parent / ".video2pr_install.json"
    if not config_path.exists():
        print("CHECK_SKIPPED: No .video2pr_install.json found", file=sys.stderr)
        sys.exit(0)
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict) or not isinstance(config.get("repo"), str):
        raise ValueError("Install configuration must contain a repository")
    if config.get("skill_dir") not in SKILL_MD_SOURCES:
        raise ValueError("Install configuration has an unknown skill directory")
    return config


def fetch_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "video2pr-updater"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    """Fetch text content from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "video2pr-updater"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def check(config: dict) -> bool:
    """Compare installed payload bytes with one immutable upstream revision."""
    revision = remote_revision(config)
    if not config.get("installed_revision"):
        print("UPDATE_AVAILABLE: Installation revision is unknown; run --apply to refresh.")
        return True
    if revision == config["installed_revision"]:
        print("UP_TO_DATE")
        return False
    # Compare the installed payload, not unrelated repository changes. This also
    # works for divergent branches and avoids GitHub compare-API pagination.
    base = GITHUB_RAW.format(repo=config["repo"], branch=revision, path="scripts/check_update.py")
    updater_text = fetch_text(base)
    names = remote_script_names(updater_text)
    import hashlib

    hashes = config.get("file_hashes", {})
    for source, destination in payload_files(config["skill_dir"], names):
        content = (
            updater_text
            if source == "scripts/check_update.py"
            else fetch_text(GITHUB_RAW.format(repo=config["repo"], branch=revision, path=source))
        )
        if source.endswith("/SKILL.md"):
            content = rewrite_paths(content, config["skill_dir"])
        if hashes.get(destination) != hashlib.sha256(content.encode("utf-8")).hexdigest():
            print("UPDATE_AVAILABLE: Installed payload differs; run --apply to update.")
            return True
    print("UP_TO_DATE")
    return False


def remote_script_names(content: str) -> list[str]:
    """Read the new updater's literal manifest without executing downloaded code."""
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        raise ValueError("Downloaded updater is not valid Python") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SCRIPT_NAMES" for t in node.targets
        ):
            names = ast.literal_eval(node.value)
            if (
                isinstance(names, list)
                and names
                and all(
                    isinstance(n, str)
                    and Path(n).name == n
                    and n.endswith(".py")
                    and "/" not in n
                    and "\\" not in n
                    for n in names
                )
                and len(set(names)) == len(names)
                and "check_update.py" in names
            ):
                return names
    raise ValueError("Downloaded updater has no valid script manifest")


def rewrite_paths(content: str, skill_dir: str) -> str:
    """Rewrite script and environment paths in SKILL.md content."""
    content = content.replace("scripts/", f"{skill_dir}/scripts/")
    content = content.replace("environment.yml", f"{skill_dir}/environment.yml")
    return content


def apply_update(config: dict, script_dir: Path) -> None:
    """Stage a complete pinned payload and roll back failed replacements."""
    import hashlib

    root = project_root(script_dir, config["skill_dir"])
    revision = remote_revision(config)
    updater_text = fetch_text(
        GITHUB_RAW.format(repo=config["repo"], branch=revision, path="scripts/check_update.py")
    )
    names = remote_script_names(updater_text)
    new_config = copy.deepcopy(config)
    new_config["installed_revision"] = revision
    new_config["installed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_config["file_hashes"] = {}
    with tempfile.TemporaryDirectory(
        prefix=".video2pr-update-", dir=script_dir.parent.parent
    ) as tmp:
        stage = Path(tmp)
        replacements = []
        for source, destination in payload_files(config["skill_dir"], names):
            content = (
                updater_text
                if source == "scripts/check_update.py"
                else fetch_text(
                    GITHUB_RAW.format(repo=config["repo"], branch=revision, path=source)
                )
            )
            if source.endswith(".py"):
                compile(content, source, "exec")
            if source.endswith("/SKILL.md"):
                content = rewrite_paths(content, config["skill_dir"])
            data = content.encode("utf-8")
            staged = stage / destination
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(data)
            new_config["file_hashes"][destination] = hashlib.sha256(data).hexdigest()
            dest = root / destination
            if not dest.resolve().is_relative_to(root):
                raise ValueError(f"Destination escapes project: {destination}")
            replacements.append((staged, dest))
        staged_config = stage / "config.json"
        staged_config.write_text(json.dumps(new_config, indent=2) + "\n", encoding="utf-8")
        replacements.append((staged_config, script_dir.parent / ".video2pr_install.json"))
        replace_paths(replacements)
    config.clear()
    config.update(new_config)
    print(f"UPDATED: {len(replacements) - 1} files at {revision}")


def main():
    parser = argparse.ArgumentParser(description="Check for video2pr updates")
    parser.add_argument("--apply", action="store_true", help="Download and apply available updates")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    try:
        config = load_config(script_dir)
        if args.apply:
            apply_update(config, script_dir)
        else:
            check(config)
    except (urllib.error.URLError, OSError, ValueError, KeyError, SyntaxError) as e:
        if args.apply:
            print(f"UPDATE_FAILED: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"CHECK_SKIPPED: {e}")


if __name__ == "__main__":
    main()
