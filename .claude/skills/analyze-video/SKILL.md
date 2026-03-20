---
name: analyze-video
description: Process a meeting recording into coding context. Extracts audio, transcribes with timestamps, and produces a structured summary. Frames can be extracted on-demand when visual content is referenced.
argument-hint: <path-to-video-file>
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
---

# Analyze Video

Process a meeting recording into a transcript with timestamps and a structured summary.

## Phase 1: Dependency Check

Run the dependency checker:

```bash
python ${CLAUDE_SKILL_DIR}/scripts/check_deps.py
```

If any dependencies show `MISSING:`, guide the user to install them:

```bash
conda env create -f environment.yml
conda activate video2pr
```

## Phase 2: Validate Input

The user provides a video file path as the argument. Verify:
1. The file exists
2. The format is supported (mp4, mkv, avi, mov, webm)
3. Get duration via ffprobe:

```bash
ffprobe -v quiet -print_format json -show_format "<video-path>" | python -c "import sys,json; d=float(json.load(sys.stdin)['format']['duration']); print(f'Duration: {d:.0f}s ({d/60:.1f} min)')"
```

Set up the output directory:
```bash
# Use the video filename (without extension) as the subdirectory name
mkdir -p .video2pr/<video-basename>
```

## Phase 3: Extract Audio & Transcribe

Run within the `video2pr` conda environment:

```bash
conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/extract_audio.py \
  --input "<video-path>" \
  --output-dir ".video2pr/<video-basename>"
```

```bash
conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/transcribe.py \
  --input ".video2pr/<video-basename>/audio.wav" \
  --output-dir ".video2pr/<video-basename>" \
  --model base
```

For higher accuracy (longer processing), use `--model medium` or `--model large`.

## Phase 4: Analyze Transcript

Read `.video2pr/<video-basename>/transcript.json`. This file contains:
- **Segments**: each with `start` (float seconds), `end` (float seconds), `text`
- **Words**: within each segment, entries with `word`, `start`, `end`, `probability`

Analyze the transcript to identify:

1. **Discussion topics** with timestamp ranges (start/end in HH:MM:SS)
2. **Visual references** — phrases like "as you can see", "this slide shows", "let me show you", "on the screen", "this diagram", etc. Use the word-level `start` time to get precise timestamps for frame extraction.
3. **Action items** — tasks assigned to people, deadlines mentioned
4. **Decisions** — conclusions reached, agreements made
5. **Feature requests** — new features or changes discussed

## Phase 5: Generate Summary

Write `.video2pr/<video-basename>/summary.md` with this structure:

```markdown
# Meeting Summary: <video-basename>

## Overview
<Brief 2-3 sentence summary of the meeting>

## Topics Discussed

### 1. <Topic Name> (HH:MM:SS - HH:MM:SS)
<Summary of discussion>

### 2. <Topic Name> (HH:MM:SS - HH:MM:SS)
<Summary of discussion>

## Visual References
For each visual reference found in the transcript, include:

| Timestamp | Context | Extract Command |
|-----------|---------|-----------------|
| HH:MM:SS | "what was said about the visual" | `conda run -n video2pr python <skill-dir>/scripts/extract_frame.py --input "<video>" --output-dir ".video2pr/<basename>" --timestamp HH:MM:SS` |

## Action Items
- [ ] <action> — assigned to <person> (HH:MM:SS)

## Decisions
- <decision made> (HH:MM:SS)

## Feature Requests
- <feature described> (HH:MM:SS)
```

**Do NOT extract frames at this stage.** Only include the ready-to-run commands.

## Phase 6: On-Demand Frame Extraction

When you or the user needs to see a specific frame (e.g., to understand a slide or diagram referenced in the transcript), extract it:

```bash
conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/extract_frame.py \
  --input "<video-path>" \
  --output-dir ".video2pr/<video-basename>" \
  --timestamp HH:MM:SS
```

The frame is saved to `.video2pr/<video-basename>/frames/frame_00h03m22s.png` and can be viewed directly.

## Output Checklist

After completion, confirm these files exist in `.video2pr/<video-basename>/`:
- `audio.wav` — 16kHz mono audio
- `metadata.json` — ffprobe video metadata
- `transcript.srt` — SRT transcript with timestamps
- `transcript.json` — JSON with word-level timestamps
- `summary.md` — structured meeting analysis
