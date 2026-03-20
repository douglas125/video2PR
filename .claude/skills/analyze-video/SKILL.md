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
conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/get_duration.py --input "<video-path>"
```

Set up the output directory:
```bash
# Use the video filename (without extension) as the subdirectory name
mkdir -p .video2pr/<video-basename>
```

**Check for external transcript:** Search for transcript files in the same directory as the video, matching the video basename with extensions: `.sbv`, `.vtt`, `.txt`, `.docx`. Also accept a user-provided transcript path. If found, report: "Found external transcript: meeting.vtt (MS Teams VTT format)"

## Phase 3: Extract & Transcribe

### Phase 3a: Extract Audio

Always extract audio (needed for language detection even with external transcripts):

```bash
conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/extract_audio.py \
  --input "<video-path>" \
  --output-dir ".video2pr/<video-basename>"
```

### Phase 3b: Check for External Transcript

If an external transcript was found in Phase 2:

- **With timestamps** → Convert and skip Whisper, go to Phase 3d:
  ```bash
  conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/convert_transcript.py \
    --input "<transcript-path>" \
    --output-dir ".video2pr/<video-basename>"
  ```

- **Without timestamps** → Convert to get speaker info, then continue to Phase 3c for Whisper transcription:
  ```bash
  conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/convert_transcript.py \
    --input "<transcript-path>" \
    --output-dir ".video2pr/<video-basename>"
  ```

If no external transcript → continue to Phase 3c.

### Phase 3c: Language Detection + Whisper Transcription

1. Detect language (always uses base model for speed):
   ```bash
   conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/transcribe.py \
     --input ".video2pr/<video-basename>/audio.wav" \
     --detect-language
   ```
   Report: "Detected language: English (95% confidence)"

2. If confidence < 80%, ask the user to confirm the language before proceeding.

3. Run full transcription with the confirmed language:
   ```bash
   conda run -n video2pr python ${CLAUDE_SKILL_DIR}/scripts/transcribe.py \
     --input ".video2pr/<video-basename>/audio.wav" \
     --output-dir ".video2pr/<video-basename>" \
     --model small \
     --language <confirmed-language-code>
   ```

The default model is `small` (good balance of speed and accuracy). For faster but less accurate results use `--model base`; for higher accuracy (longer processing) use `--model medium` or `--model large`.

### Phase 3d: Speaker Enrichment (conditional)

If an external transcript WITHOUT timestamps was used AND Whisper ran in Phase 3c: match text between the Whisper output and the external transcript to add `speaker` fields to the Whisper segments. This is done by Claude directly (no script needed) — compare overlapping text to attribute speakers from the external transcript to Whisper's timestamped segments.

## Phase 4: Analyze Transcript

Read `.video2pr/<video-basename>/transcript.json`. This file contains:
- **Segments**: each with `start` (float seconds), `end` (float seconds), `text`, optionally `speaker`
- **Words**: within each segment, entries with `word`, `start`, `end`, `probability` (may be empty for external transcripts)

When `speaker` fields are available, use them to attribute topics, action items, and decisions to specific speakers.

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
- `transcript.json` — JSON with segment timestamps (and word-level if Whisper-generated)
- `transcript.srt` — SRT transcript with timestamps (Whisper-generated only)
- `summary.md` — structured meeting analysis
- `external_transcript_meta.json` — (if external transcript used) source format and capabilities
- `external_transcript_original.*` — (if external transcript used) copy of original file
