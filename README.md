# video2PR

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that converts meeting video recordings into structured context for coding assistants — transcripts with timestamps, speaker attribution, action items, and decisions.

## Getting Started

### 1. Install dependencies

```bash
conda env create -f environment.yml
conda activate video2pr
```

### 2. Install the skill

Copy `.claude/skills/analyze-video/` into your project's `.claude/skills/` directory:

```bash
cp -r .claude/skills/analyze-video /path/to/your-project/.claude/skills/
```

Also copy `environment.yml` if your project doesn't already have one.

### 3. Run it

In Claude Code, from your project directory:

```
/analyze-video path/to/meeting.mp4
```

Output goes to `.video2pr/<video-name>/` (add `.video2pr/` to your `.gitignore`).

## What It Does

1. Extracts audio from video (mp4, mkv, avi, mov, webm)
2. Detects spoken language with confidence scoring — asks for confirmation if < 80%
3. Transcribes via Whisper with word-level timestamps, or imports an external transcript (Google Meet SBV/TXT, MS Teams VTT/DOCX) with speaker attribution
4. Produces `summary.md` with topics, action items, decisions, and visual reference commands

If a transcript file sits next to the video (same name, `.sbv`/`.vtt`/`.txt`/`.docx` extension), it's picked up automatically.

## Standalone Scripts

```bash
# Detect language
conda run -n video2pr python .claude/skills/analyze-video/scripts/transcribe.py \
  --input audio.wav --detect-language

# Transcribe with explicit language
conda run -n video2pr python .claude/skills/analyze-video/scripts/transcribe.py \
  --input audio.wav --output-dir out --model base --language en

# Convert an external transcript
conda run -n video2pr python .claude/skills/analyze-video/scripts/convert_transcript.py \
  --input meeting.vtt --output-dir out
```

## Output Files

| File | Description |
|------|-------------|
| `audio.wav` | 16kHz mono audio |
| `metadata.json` | ffprobe video metadata |
| `transcript.json` | Segments with timestamps, text, optional speaker/word data |
| `transcript.srt` | SRT subtitles (Whisper-generated only) |
| `summary.md` | Structured meeting analysis |
| `external_transcript_meta.json` | Source format info (external transcript only) |
| `external_transcript_original.*` | Copy of original transcript (external only) |
