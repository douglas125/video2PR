# video2PR

An AI coding assistant skill that converts meeting video recordings into structured context - transcripts with timestamps, speaker attribution, action items, decisions, and a codebase-grounded implementation plan. Works with Claude Code, OpenAI Codex CLI, and GitHub Copilot CLI.

## Cross-Platform Support

video2PR works with multiple AI coding assistants:

| Platform | Skill location | Status |
|----------|---------------|--------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `.claude/skills/video2pr/` | Full support |
| [OpenAI Codex CLI](https://github.com/openai/codex) | `.agents/skills/video2pr/` | Full support |
| [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli) | `.github/skills/video2pr/` | Full support |

Each skill folder is fully self-contained - SKILL.md, scripts, and environment.yml are all included.

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

Each skill folder is fully self-contained - scripts and environment.yml are copied alongside the SKILL.md. No files are placed outside the skill folder.

### Updating

The skill checks for updates on each run and notifies you if a newer version is available. To apply, run the updater from the skill directory you installed:

```bash
conda run -n video2pr python .claude/skills/video2pr/scripts/check_update.py --apply
conda run -n video2pr python .agents/skills/video2pr/scripts/check_update.py --apply
conda run -n video2pr python .github/skills/video2pr/scripts/check_update.py --apply
```

<details>
<summary>Manual installation</summary>

Manual install is a folder copy, and the source/destination paths are the same on Windows, macOS, and Linux:

- Claude Code: copy `.claude/skills/video2pr/` into `<project>/.claude/skills/video2pr/`
- Codex CLI: copy `.agents/skills/video2pr/` into `<project>/.agents/skills/video2pr/`
- GitHub Copilot CLI: copy `.github/skills/video2pr/` into `<project>/.github/skills/video2pr/`
- GitHub Copilot CLI: also copy `.github/agents/video2pr.agent.md` into `<project>/.github/agents/video2pr.agent.md`

</details>

### 3. Run it

In your coding assistant, from your project directory:

```
/video2pr path/to/meeting.mp4
```

Output goes to `.video2pr/<video-name>/` (add `.video2pr/` to your `.gitignore`).

## What It Does

1. Extracts audio from video (mp4, mkv, avi, mov, webm)
2. Detects spoken language with confidence scoring - asks for confirmation if < 80%
3. Transcribes via Whisper with word-level timestamps, or imports an external transcript (Google Meet SBV/TXT, MS Teams VTT/DOCX, Zoom VTT/TXT) with speaker attribution
4. Analyzes the codebase against what was discussed and produces a concrete implementation plan (`plan.md`)
5. Produces `summary.md` with topics, action items, decisions, visual reference commands, and a link to the implementation plan
6. Optionally creates GitHub Issues from plan tasks (each confirmed individually before creation)

If a transcript file sits next to the video (same name, `.sbv`/`.vtt`/`.txt`/`.docx` extension), it's picked up automatically. Zoom, Google Meet, and MS Teams transcript formats are all auto-detected.

## Whisper Model Choices

The `--model` flag controls the quality/speed tradeoff for transcription:

| Model | Parameters | Relative Speed | Best For |
|-------|-----------|----------------|----------|
| `base` | 74M | ~10x realtime | Quick drafts, testing, short meetings |
| `small` | 244M | ~4x realtime | **Default** - good balance of speed and accuracy |
| `medium` | 769M | ~1.5x realtime | Important meetings where accuracy matters |
| `large-v3` | 1550M | ~0.5x realtime | Maximum accuracy, multilingual content |
| `turbo` | 809M | ~3x realtime | Fast with good accuracy (faster-whisper only) |

Speed estimates assume GPU acceleration. CPU-only runs are roughly 5-20x slower. The skill prompts you to install CUDA support if a compatible GPU is detected but not configured.

## Standalone Scripts

```bash
# Detect language
conda run -n video2pr python scripts/transcribe.py --input audio.wav --detect-language

# Transcribe with explicit language and device selection
conda run -n video2pr python scripts/transcribe.py --input audio.wav --output-dir out --model small --language en --device auto

# Convert an external transcript
conda run -n video2pr python scripts/convert_transcript.py --input meeting.vtt --output-dir out
```

## Output Files

| File | Description |
|------|-------------|
| `audio.wav` | 16kHz mono audio |
| `metadata.json` | ffprobe video metadata |
| `transcript.json` | Segments with timestamps, text, optional speaker/word data |
| `transcript.srt` | SRT subtitles (Whisper-generated only) |
| `plan.md` | Codebase-grounded implementation plan with prioritized tasks |
| `progress.md` | Task completion tracker (persists across runs) |
| `summary.md` | Structured meeting analysis with implementation plan summary |
| `external_transcript_meta.json` | Source format info (external transcript only) |
| `external_transcript_original.*` | Copy of original transcript (external only) |
