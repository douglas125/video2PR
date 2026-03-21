# video2PR

An AI coding assistant skill that converts meeting video recordings into structured context — transcripts with timestamps, speaker attribution, action items, decisions, and a codebase-grounded implementation plan. Works with Claude Code, OpenAI Codex CLI, and GitHub Copilot CLI.

## Cross-Platform Support

video2PR works with multiple AI coding assistants:

| Platform | Skill location | Status |
|----------|---------------|--------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `.claude/skills/video2pr/` | Full support |
| [OpenAI Codex CLI](https://github.com/openai/codex) | `.agents/skills/video2pr/` | Full support |
| [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli) | `.github/skills/video2pr/` | Full support |

Each skill folder is fully self-contained — SKILL.md, scripts, and environment.yml are all included.

## Getting Started

### 1. Install dependencies

```bash
conda env create -f environment.yml
```

The agent runs commands via `conda run -n video2pr`, so `conda activate` is not needed.

### 2. Install the skill

```bash
# Install to your project (all assistants)
python /path/to/video2PR/install_video2pr.py /path/to/your-project

# Install for specific assistants only
python /path/to/video2PR/install_video2pr.py /path/to/your-project --assistants claude-code

# Preview what will be installed
python /path/to/video2PR/install_video2pr.py /path/to/your-project --dry-run
```

Each skill folder is fully self-contained — scripts and environment.yml are copied alongside the SKILL.md. No files are placed outside the skill folder.

### Updating

The skill checks for updates on each run and notifies you if a newer version is available. To apply:

```bash
conda run -n video2pr python .claude/skills/video2pr/scripts/check_update.py --apply
```

<details>
<summary>Manual installation</summary>

```bash
# Copy the skill folder for your platform into your project:

# Claude Code
cp -r .claude/skills/video2pr /path/to/your-project/.claude/skills/

# Codex CLI
cp -r .agents/skills/video2pr /path/to/your-project/.agents/skills/

# Copilot CLI
cp -r .github/skills/video2pr /path/to/your-project/.github/skills/
mkdir -p /path/to/your-project/.github/agents
cp .github/agents/video2pr.agent.md /path/to/your-project/.github/agents/
```

</details>

### 3. Run it

In your coding assistant, from your project directory:

```
/video2pr path/to/meeting.mp4
```

Output goes to `.video2pr/<video-name>/` (add `.video2pr/` to your `.gitignore`).

## What It Does

1. Extracts audio from video (mp4, mkv, avi, mov, webm)
2. Detects spoken language with confidence scoring — asks for confirmation if < 80%
3. Transcribes via Whisper with word-level timestamps, or imports an external transcript (Google Meet SBV/TXT, MS Teams VTT/DOCX) with speaker attribution
4. Analyzes the codebase against what was discussed and produces a concrete implementation plan (`plan.md`)
5. Produces `summary.md` with topics, action items, decisions, visual reference commands, and a link to the implementation plan

If a transcript file sits next to the video (same name, `.sbv`/`.vtt`/`.txt`/`.docx` extension), it's picked up automatically.

## Standalone Scripts

```bash
# Detect language
conda run -n video2pr python scripts/transcribe.py \
  --input audio.wav --detect-language

# Transcribe with explicit language
conda run -n video2pr python scripts/transcribe.py \
  --input audio.wav --output-dir out --model base --language en

# Convert an external transcript
conda run -n video2pr python scripts/convert_transcript.py \
  --input meeting.vtt --output-dir out
```

## Output Files

| File | Description |
|------|-------------|
| `audio.wav` | 16kHz mono audio |
| `metadata.json` | ffprobe video metadata |
| `transcript.json` | Segments with timestamps, text, optional speaker/word data |
| `transcript.srt` | SRT subtitles (Whisper-generated only) |
| `plan.md` | Codebase-grounded implementation plan with prioritized tasks |
| `summary.md` | Structured meeting analysis with implementation plan summary |
| `external_transcript_meta.json` | Source format info (external transcript only) |
| `external_transcript_original.*` | Copy of original transcript (external only) |
