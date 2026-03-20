# video2PR

Converts meeting video recordings into structured context for coding assistants.

## Setup

```bash
conda env create -f environment.yml
conda activate video2pr
```

## Usage

Use the `/video2pr <path>` skill to process a video recording.

## Project Structure

- `environment.yml` — Conda environment definition
- `scripts/` — Platform-neutral Python scripts (audio extraction, transcription, etc.)
- `.claude/skills/video2pr/` — Claude Code skill definition (SKILL.md only)
- `.agents/skills/video2pr/` — Codex CLI skill definition
- `.github/skills/video2pr/` — Copilot CLI skill definition
- `.github/agents/` — Copilot agent definition
- `.video2pr/` — Runtime output directory (per-video, gitignored)

## Git Workflow

Always create a feature branch from `main`, open a PR, then merge to `main`. Never commit directly to `main`.
