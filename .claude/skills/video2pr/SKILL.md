---
name: video2pr
description: >-
  Convert a meeting recording into an actionable implementation plan.
  Extracts audio, transcribes with timestamps, analyzes the codebase
  against what was discussed, and produces a concrete plan of what to
  build or change. Argument: path to a video file.
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - EnterPlanMode
  - ExitPlanMode
---

# video2pr

Process a meeting recording into a transcript, structured summary, and codebase-grounded implementation plan.

**Important — scope rules:**
- The **codebase** is the repository root (the current working directory where this skill is invoked). All file scanning, analysis, and modifications must stay within this repository.
- The video file path is an **input artifact only**. Its parent directory is unrelated to the codebase — do not scan, analyze, or modify files there.
- The only new directory created is `.video2pr/` inside the repo root for output files.

## Phase 0: Check for Updates

Run the update checker:

```bash
conda run -n video2pr python scripts/check_update.py
```

- If output contains `UP_TO_DATE` or `CHECK_SKIPPED`: continue to Phase 1 silently.
- If output contains `UPDATE_AVAILABLE`: tell the user: "A video2pr update is available. To update, run: `conda run -n video2pr python scripts/check_update.py --apply`". Then continue to Phase 1 — do NOT auto-update.

## Phase 1: Dependency Check

Run the dependency checker:

```bash
python scripts/check_deps.py
```

If any dependencies show `MISSING:`, guide the user to install them:

```bash
conda env create -f environment.yml
conda activate video2pr
```

After dependencies pass, check GPU status:

```bash
conda run -n video2pr python scripts/check_gpu.py
```

Interpret the JSON output:
- If `torch_device_available` is `true`: report the GPU (e.g., "GPU acceleration: NVIDIA RTX 3080 via CUDA 12.4") and continue.
- If `torch_device_available` is `false` and `install_command` is not null: tell the user their GPU can be used but PyTorch can't access it. Show the install command and note the approximate speedup (~5-20x). Ask if they want to install it now or continue with CPU. Do NOT auto-install.
- If `device` is `"cpu"` and `install_command` is null: note "Running on CPU" and continue silently.

## Phase 2: Validate Input

The user provides a video file path as the argument. Verify:
1. The file exists
2. The format is supported (mp4, mkv, avi, mov, webm)
3. Get duration via ffprobe:

```bash
conda run -n video2pr python scripts/get_duration.py --input "<video-path>"
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
conda run -n video2pr python scripts/extract_audio.py \
  --input "<video-path>" \
  --output-dir ".video2pr/<video-basename>"
```

### Phase 3b: Check for External Transcript

If an external transcript was found in Phase 2:

- **With timestamps** → Convert and skip Whisper, go to Phase 3d:
  ```bash
  conda run -n video2pr python scripts/convert_transcript.py \
    --input "<transcript-path>" \
    --output-dir ".video2pr/<video-basename>"
  ```

- **Without timestamps** → Convert to get speaker info, then continue to Phase 3c for Whisper transcription:
  ```bash
  conda run -n video2pr python scripts/convert_transcript.py \
    --input "<transcript-path>" \
    --output-dir ".video2pr/<video-basename>"
  ```

If no external transcript → continue to Phase 3c.

### Phase 3c: Language Detection + Whisper Transcription

1. Detect language (always uses base model for speed):
   ```bash
   conda run -n video2pr python scripts/transcribe.py \
     --input ".video2pr/<video-basename>/audio.wav" \
     --detect-language
   ```
   Report: "Detected language: English (95% confidence)"

2. If confidence < 80%, ask the user to confirm the language before proceeding.

3. Run full transcription with the confirmed language:
   ```bash
   conda run -n video2pr python scripts/transcribe.py \
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

## Phase 5: Codebase Analysis & Implementation Plan

This phase bridges the meeting discussion with the actual codebase, producing a concrete plan of what to build or change.

### Step 5a: Extract Actionable Items

From the Phase 4 analysis, extract every actionable item discussed. Categorize each as one of:
- **requirement** — something that must be built or satisfied
- **feature request** — a new capability or enhancement
- **bug report** — a defect or unexpected behavior described
- **refactoring** — restructuring existing code without changing behavior
- **architecture change** — significant structural change to the system
- **config change** — environment, deployment, or configuration update
- **documentation** — docs, comments, or knowledge-base updates

For each item, record:
- Title (concise)
- Speaker and timestamp (from transcript)
- One-sentence description
- Verbatim transcript excerpt (1-3 sentences, copied exactly from the transcript) with start/end timestamps — this grounds the task in what was actually said

### Step 5b: Scan Codebase

For each actionable item, use Glob and Read to search the codebase **within the repository root** — not the video file's directory. Classify each item:

- **Already exists** — the functionality or fix is already in place. Cite specific file paths and function/class names.
- **Partially exists** — some relevant code exists but gaps remain. Cite existing code and describe what's missing.
- **New** — nothing relevant found. Confirm what was searched (patterns, directories) and not found.
- **Not applicable** — the item doesn't apply to this codebase (e.g., refers to an external system). Explain why.

### Step 5c: Build Implementation Plan

Create an ordered list of tasks, each with:
- **Priority**: P0-Blocker, P1-High, P2-Medium, P3-Low
- **Status**: from Step 5b (already exists / partially exists / new / not applicable)
- **Affected files**: specific file paths that need to be created or modified
- **Approach**: 2-5 sentences describing the concrete implementation approach
- **Dependencies**: references to other tasks that must be completed first (if any)
- **Complexity**: Small (< 1 hour), Medium (1-4 hours), Large (4+ hours)

Ordering: P0 items first, then within each priority level, dependency-free tasks before dependent ones.

### Step 5d: Write plan.md

Write the implementation plan to `.video2pr/<video-basename>/plan.md` with:

```markdown
# Implementation Plan: <video-basename>

## Summary

| # | Task | Priority | Status | Complexity | Dependencies |
|---|------|----------|--------|------------|--------------|
| 1 | <title> | P0 | New | Medium | — |
| 2 | <title> | P1 | Partial | Small | #1 |

## Tasks

### Task 1: <title>
- **Priority**: P0-Blocker
- **Status**: New
- **Affected files**: `src/foo.py`, `src/bar.py`
- **Approach**: <2-5 sentences>
- **Dependencies**: None
- **Complexity**: Medium
- **Source**: <speaker> at HH:MM:SS — "<one-sentence description>"
- **Transcript excerpt** (HH:MM:SS–HH:MM:SS):
  > "verbatim quote from the transcript that motivated this task, 1-3 sentences copied exactly"

### Task 2: <title>
...

## Dependency Graph
(Include only if any tasks have dependencies)

Task 1 → Task 2 → Task 4
Task 3 (independent)

## Not Applicable Items
(Include only if any items were classified as not applicable)

- <item> — <reason>
```

### Step 5e: Enter Plan Mode

After writing `plan.md`, use `EnterPlanMode` to present the implementation plan to the user for review. Walk through the proposed tasks, highlight the top priorities, and let the user approve, adjust, or reprioritize before moving on to Phase 6 (summary generation). Use `ExitPlanMode` once the user confirms the plan.

## Phase 6: Generate Summary

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
| HH:MM:SS | "what was said about the visual" | `conda run -n video2pr python scripts/extract_frame.py --input "<video>" --output-dir ".video2pr/<basename>" --timestamp HH:MM:SS` |

## Implementation Plan

See [plan.md](plan.md) for the full implementation plan.

**Items by status:**
- New: <count>
- Partially exists: <count>
- Already exists: <count>
- Not applicable: <count>

**Top priorities:**
- [ ] <P0/P1 task title> (Task #<n>)
- [ ] <P0/P1 task title> (Task #<n>)

## Action Items
- [ ] <action> — assigned to <person> (HH:MM:SS)

## Decisions
- <decision made> (HH:MM:SS)

## Feature Requests
- <feature described> (HH:MM:SS) → Plan Task #<n>
```

**Do NOT extract frames at this stage.** Only include the ready-to-run commands.

## Frame Extraction (utility — available anytime)

At any point during Phase 4, Phase 5, or later during implementation, you can extract a frame from the video when visual context would help understand what was discussed:

```bash
conda run -n video2pr python scripts/extract_frame.py \
  --input "<video-path>" \
  --output-dir ".video2pr/<video-basename>" \
  --timestamp HH:MM:SS
```

The frame is saved to `.video2pr/<video-basename>/frames/frame_00h03m22s.png` and can be viewed directly.

## Output Checklist

After completion, confirm these files exist in `.video2pr/<video-basename>/`:

**Always created:**
- `audio.wav` — 16kHz mono audio
- `metadata.json` — ffprobe video metadata
- `transcript.json` — JSON with segment timestamps (and word-level if Whisper-generated)
- `plan.md` — codebase-grounded implementation plan
- `summary.md` — structured meeting analysis with implementation plan summary

**Created only when Whisper transcription was used (no external transcript with timestamps):**
- `transcript.srt` — SRT transcript with timestamps

**Created only when an external transcript was provided:**
- `external_transcript_meta.json` — source format and capabilities
- `external_transcript_original.*` — copy of original file

## Phase 7: Offer to Implement

After the output checklist passes, present the top-priority tasks from `plan.md` and offer to begin implementation:

1. List all P0 and P1 tasks with their titles and affected files
2. Ask the user which task(s) to start with
3. Only begin implementation after the user explicitly selects task(s)

When implementing a task:
- Follow the approach described in `plan.md`
- Respect dependency ordering — do not start a task whose dependencies are incomplete
- Work within the repository root (same scope rules as Phase 5)
- After completing each task, report what was changed and ask whether to continue with the next task
