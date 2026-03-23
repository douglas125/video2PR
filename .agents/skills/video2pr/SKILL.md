---
name: video2pr
description: >-
  Convert a meeting recording into an actionable implementation plan.
  Extracts audio, transcribes with timestamps, analyzes the codebase
  against what was discussed, and produces a concrete plan of what to
  build or change. Argument: path to a video file.
license: MIT
compatibility: "Requires conda, ffmpeg, and Python 3.13+. Install with: conda env create -f environment.yml"
metadata:
  author: douglas125
  version: "1.0"
allowed-tools: shell read_file apply_patch list_dir grep_files
---

# video2pr

Process a meeting recording into a transcript, structured summary, and codebase-grounded implementation plan.

**Important - scope rules:**
- The **codebase** is the repository root (the current working directory where this skill is invoked). All file scanning, analysis, and modifications must stay within this repository.
- The video file path is an **input artifact only**. Its parent directory is unrelated to the codebase - do not scan, analyze, or modify files there.
- The only new directory created is `.video2pr/` inside the repo root for output files.
- **Never reference this skill's internal workflow, phase names, or mechanics in user-facing output.** Do not say things like "the skill requires...", "per Phase 5...", or "the workflow pauses here for...". Communicate naturally about the work itself (e.g., "here's the implementation plan" not "Phase 5e requires plan approval").

## Phase 0: Check for Updates

Run the update checker:

```bash
conda run -n video2pr python scripts/check_update.py
```

- If output contains `UP_TO_DATE` or `CHECK_SKIPPED`: continue to Phase 1 silently.
- If output contains `UPDATE_AVAILABLE`: display a **prominent warning** that a video2pr update is available and **ask whether to update now or continue with the current version**. Wait for the user's response. If they agree, run `conda run -n video2pr python scripts/check_update.py --apply` directly - do NOT just show the command for the user to run manually. Then continue to Phase 1.

## Phase 1: Dependency Check

Run the dependency checker:

```bash
python scripts/check_deps.py
```

**Capture the conda path:** Look for the `CONDA_PATH: <path>` line in the output. Use that path instead of bare `conda` in **all** subsequent commands in this skill (e.g., `<conda-path> run -n video2pr ...`). If no `CONDA_PATH:` line appears (e.g., conda is missing), use `conda` as-is.

If any dependencies show `MISSING:`, guide the user to install them:

```bash
conda env create -f environment.yml
```

After dependencies pass, check GPU status:

```bash
<conda-path> run -n video2pr python scripts/check_gpu.py
```

Interpret the JSON output:
- If `torch_device_available` is `true`: report the GPU (e.g., "GPU acceleration: NVIDIA RTX 3080 via CUDA 12.4") and continue.
- If `torch_device_available` is `false` and `install_command` is not null: briefly note that GPU is available but PyTorch can't use it yet. Do NOT prompt to install here — the actionable prompt will appear in Phase 3.3, right before transcription when it matters most.
- If `device` is `"cpu"` and `install_command` is null: note "Running on CPU" and continue silently.

## Phase 2: Validate Input

The user provides a video file path as the argument. Verify:
1. The file exists
2. The format is supported (mp4, mkv, avi, mov, webm)
3. Get duration via ffprobe:

```bash
conda run -n video2pr python scripts/get_duration.py --input "<video-path>"
```

Set up the output directory by creating `.video2pr/<video-basename>/` if it does not already exist. Use the video filename (without extension) as the subdirectory name.

**Check for existing outputs:** After creating the output directory, check whether prior runs already produced files in `.video2pr/<video-basename>/`:
- If `transcript.json` exists: report "Found existing transcription from a previous run" and ask the user whether to reuse it or re-transcribe. If reusing, skip Phases 3.1-3.4 entirely and go to Phase 4.
- If `audio.wav` exists but `transcript.json` does not: report "Found previously extracted audio" and ask whether to reuse it. If reusing, skip Phase 3.1.
- If `plan.md` or `summary.md` exist: note their presence but always regenerate them (codebase may have changed).
- If `progress.md` exists: report "Found progress tracker from previous run(s) — N of M tasks completed" (read the file to get counts). This file will be used in Phase 5 to carry forward completion status.

**Check for external transcript:** Search for transcript files in the same directory as the video, matching the video basename with extensions: `.sbv`, `.vtt`, `.txt`, `.docx`. Also accept a user-provided transcript path. If found, report: "Found external transcript: meeting.vtt (MS Teams VTT format)"

## Phase 3: Extract & Transcribe

### Phase 3.1: Extract Audio

Always extract audio (needed for language detection even with external transcripts):

```bash
conda run -n video2pr python scripts/extract_audio.py --input "<video-path>" --output-dir ".video2pr/<video-basename>"
```

### Phase 3.2: Check for External Transcript

If an external transcript was found in Phase 2:

- **With timestamps** -> Convert and skip Whisper, go to Phase 3.4:
  ```bash
  conda run -n video2pr python scripts/convert_transcript.py --input "<transcript-path>" --output-dir ".video2pr/<video-basename>"
  ```

- **Without timestamps** -> Convert to get speaker info, then continue to Phase 3.3 for Whisper transcription:
  ```bash
  conda run -n video2pr python scripts/convert_transcript.py --input "<transcript-path>" --output-dir ".video2pr/<video-basename>"
  ```

If no external transcript -> continue to Phase 3.3.

### Phase 3.3: Language Detection + Whisper Transcription

**Pre-transcription check:** Before starting transcription (the longest step), re-check GPU status and surface any pending notices so the user can act on them before waiting:

Run GPU check: `conda run -n video2pr python scripts/check_gpu.py`

- If `torch_device_available` is `false` AND `install_command` is not null: display a **prominent warning** to the user explaining that their GPU is available but not being used, note the ~5-20x speedup, and **ask whether to install GPU-accelerated PyTorch now or continue with CPU**. Wait for the user's response. If they agree, run the install command directly (e.g., `conda run -n video2pr <install_command>`) - do NOT just show the command for the user to run manually. After installation, re-run `check_gpu.py` to confirm GPU support is active before proceeding.
- Otherwise, continue silently.

1. Detect language (always uses base model for speed):
   ```bash
   conda run -n video2pr python scripts/transcribe.py --input ".video2pr/<video-basename>/audio.wav" --detect-language
   ```
   Report: "Detected language: English (95% confidence)"

2. If confidence < 80%, ask the user to confirm the language before proceeding.

3. Run full transcription with the confirmed language:
   ```bash
   conda run -n video2pr python scripts/transcribe.py --input ".video2pr/<video-basename>/audio.wav" --output-dir ".video2pr/<video-basename>" --model small --language <confirmed-language-code>
   ```

The default model is `small` (good balance of speed and accuracy). For faster but less accurate results use `--model base`; for higher accuracy (longer processing) use `--model medium` or `--model large`.

### Phase 3.4: Speaker Enrichment (conditional)

If an external transcript WITHOUT timestamps was used AND Whisper ran in Phase 3.3: match text between the Whisper output and the external transcript to add `speaker` fields to the Whisper segments. This is done directly (no script needed) - compare overlapping text to attribute speakers from the external transcript to Whisper's timestamped segments.

## Phase 4: Analyze Transcript

Read `.video2pr/<video-basename>/transcript.json`. This file contains:
- **Segments**: each with `start` (float seconds), `end` (float seconds), `text`, optionally `speaker`
- **Words**: within each segment, entries with `word`, `start`, `end`, `probability` (may be empty for external transcripts)

When `speaker` fields are available, use them to attribute topics, action items, and decisions to specific speakers.

Analyze the transcript to identify:

1. **Discussion topics** with timestamp ranges (start/end in HH:MM:SS)
2. **Visual references** - phrases like "as you can see", "this slide shows", "let me show you", "on the screen", "this diagram", etc. Use the word-level `start` time to get precise timestamps for frame extraction. **When visual references are identified, extract and read frames at those timestamps if the visual context would help understand the discussion.** Use judgment — sometimes no frames are needed, sometimes several are. Don't defer this to later phases; understanding what was shown on screen often informs the implementation plan.
3. **Action items** - tasks assigned to people, deadlines mentioned
4. **Decisions** - conclusions reached, agreements made
5. **Feature requests** - new features or changes discussed

After completing this analysis, proceed directly to Phase 5. Do NOT ask for user approval or enter plan mode at this stage — the plan review checkpoint comes after the codebase analysis in Phase 5. Move through Phase 5 efficiently; do not linger between phases.

## Phase 5: Codebase Analysis & Implementation Plan

This phase bridges the meeting discussion with the actual codebase, producing a concrete plan of what to build or change.

### Step 5.1: Extract Actionable Items

From the Phase 4 analysis, extract every actionable item discussed. Categorize each as one of:
- **requirement** - something that must be built or satisfied
- **feature request** - a new capability or enhancement
- **bug report** - a defect or unexpected behavior described
- **refactoring** - restructuring existing code without changing behavior
- **architecture change** - significant structural change to the system
- **config change** - environment, deployment, or configuration update
- **documentation** - docs, comments, or knowledge-base updates

For each item, record:
- Title (concise)
- Speaker and timestamp (from transcript)
- One-sentence description
- Verbatim transcript excerpt (1-3 sentences, copied exactly from the transcript) with start/end timestamps — this grounds the task in what was actually said

### Step 5.2: Scan Codebase

For each actionable item, search the codebase **within the repository root** using file listing and content search tools — not the video file's directory. Classify each item:

- **Already exists** - the functionality or fix is already in place. Cite specific file paths and function/class names.
- **Partially exists** - some relevant code exists but gaps remain. Cite existing code and describe what's missing.
- **New** - nothing relevant found. Confirm what was searched (patterns, directories) and not found.
- **Not applicable** - the item doesn't apply to this codebase (e.g., refers to an external system). Explain why.

### Step 5.3: Reconcile with Existing Progress (conditional)

If `.video2pr/<video-basename>/progress.md` exists from a prior run:

1. Read `progress.md` and extract tasks marked `[x]` (completed).
2. For each completed task, match it to the current plan's tasks by **title** (fuzzy match — titles may vary slightly across regenerations; use transcript excerpt as tiebreaker if titles are ambiguous).
   - If the codebase scan (Step 5.2) confirms the code still exists → carry forward the `[x]` completion marker.
   - If the code was removed or reverted → clear the marker (task needs re-implementation).
3. Completed tasks in old progress that have no match in the new plan → archive them in a "Previously Completed (no longer in plan)" note at the bottom of `progress.md` for reference. Do not add them back to the plan.

### Step 5.4: Build Implementation Plan

Create an ordered list of tasks, each with:
- **Priority**: P0-Blocker, P1-High, P2-Medium, P3-Low
- **Status**: from Step 5.2 (already exists / partially exists / new / not applicable)
- **Affected files**: specific file paths that need to be created or modified
- **Approach**: 2-5 sentences describing the concrete implementation approach
- **Dependencies**: references to other tasks that must be completed first (if any)
- **Complexity**: Small (< 1 hour), Medium (1-4 hours), Large (4+ hours)

Ordering: P0 items first, then within each priority level, dependency-free tasks before dependent ones.

### Step 5.5: Write plan.md

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

After writing `plan.md`, also write or update `.video2pr/<video-basename>/progress.md`:

- **First run** (no existing `progress.md`): create it from the plan. All actionable tasks start unchecked (`[ ]`). Tasks with status "already exists" or "not applicable" are marked `--`.
- **Subsequent run** (existing `progress.md`): update the Task Checklist to reflect the new plan's tasks, carrying forward `[x]` marks for tasks confirmed still implemented in Step 5.3. Increment the run counter. Preserve all existing Completion Log entries.

Format for `progress.md`:

```markdown
# Progress: <video-basename>

Last updated: YYYY-MM-DD (run #N)

## Task Checklist

| # | Task | Priority | Implemented |
|---|------|----------|-------------|
| 1 | <title> | P0 | [ ] |
| 2 | <title> | P1 | [x] Run #1 |
| 3 | <title> | P0 | -- (already exists) |

## Completion Log

### Run #1 — YYYY-MM-DD
- **Task 2**: <title> — files modified: `src/foo.py`, `src/bar.py`
```

- `[x] Run #N` = completed in run N. `[ ]` = pending. `--` = no action needed (already exists / not applicable).
- The Completion Log is append-only — each run adds a section recording what was done.

### Step 5.6: Present Plan for Review

This is the ONLY user approval checkpoint before Phase 6. After writing `plan.md` and `progress.md`, present the implementation plan for review. Walk through the proposed tasks, highlight the top priorities, and let the user approve, adjust, or reprioritize before proceeding to Phase 6.

If prior progress exists, lead the plan presentation with a progress summary: "N of M tasks from the meeting have been implemented in previous runs. Remaining: X tasks (Y high-priority)." Then present remaining tasks, with completed tasks shown but de-emphasized.

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

If `progress.md` exists, reflect completion status in this list:
- [x] <task title> (Task #<n>) — completed in Run #1
- [ ] <task title> (Task #<n>)

## Action Items
- [ ] <action> — assigned to <person> (HH:MM:SS)

## Decisions
- <decision made> (HH:MM:SS)

## Feature Requests
- <feature described> (HH:MM:SS) → Plan Task #<n>
```

Frames may already have been extracted during Phase 4. For any visual references not yet extracted, include the ready-to-run commands in the table.

## Frame Extraction (encouraged whenever visual context helps)

Extract frames proactively whenever visual context would help understand what was discussed — during transcript analysis, codebase analysis, plan writing, or implementation. Default toward extracting when visual references exist rather than deferring:

```bash
conda run -n video2pr python scripts/extract_frame.py --input "<video-path>" --output-dir ".video2pr/<video-basename>" --timestamp HH:MM:SS
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
- `progress.md` — task completion tracker (persists across runs)

**Created only when Whisper transcription was used (no external transcript with timestamps):**
- `transcript.srt` — SRT transcript with timestamps

**Created only when an external transcript was provided:**
- `external_transcript_meta.json` — source format and capabilities
- `external_transcript_original.*` — copy of original file

## Phase 7: Offer to Implement

After the output checklist passes, read `progress.md` and present remaining (uncompleted) tasks from `plan.md`, ordered by priority. If prior progress exists, note: "N tasks already completed in previous runs — showing remaining work."

1. List all incomplete P0 and P1 tasks with their titles and affected files
2. Ask the user which task(s) to start with
3. Only begin implementation after the user explicitly selects task(s)

When implementing a task:
- Follow the approach described in `plan.md`
- Respect dependency ordering — do not start a task whose dependencies are incomplete
- Work within the repository root (same scope rules as Phase 5)
- After completing each task:
  1. Mark the task as `[x] Run #N` in the `progress.md` Task Checklist
  2. Append to the Completion Log: task number, title, and files modified
  3. Report what was changed and ask whether to continue with the next task
