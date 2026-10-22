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

Each skill folder is fully self-contained - scripts and environment.yml are copied alongside the SKILL.md. Copilot also installs `.github/agents/video2pr.agent.md`.

### Updating

The skill checks dependencies, then checks for updates on each run and notifies you if a newer version is available. To apply, run the updater from the skill directory you installed:

```bash
conda run -n video2pr python .claude/skills/video2pr/scripts/check_update.py --apply
conda run -n video2pr python .agents/skills/video2pr/scripts/check_update.py --apply
conda run -n video2pr python .github/skills/video2pr/scripts/check_update.py --apply
```

Use the installer for local and offline installation. The source skill folders contain generated prompts and assistant metadata; copying them alone omits runtime scripts and path rewriting. To replace an existing installation use `--force`; replacement starts only after staging succeeds. Installation into the source repository itself is rejected.


Updates download a complete payload from one commit before replacing files. Failed downloads preserve the installation; replacement errors restore backups. Revision metadata changes only after success. Older installations without a revision are offered a refresh. Environment changes may require `conda env update -f <installed-skill>/environment.yml`.

<details>
<summary>Editing the skill prompt</summary>

The three `SKILL.md` files under `.claude/`, `.agents/`, and `.github/` are **generated** from a single canonical source at `skill/SKILL.md`. To change the prompt, edit the canonical file and regenerate the copies:

```bash
python scripts/sync_skill.py
```

CI runs `python scripts/sync_skill.py --check` and fails if the generated files drift from the source.

</details>

### 3. Run it

In your coding assistant, from your project directory:

```
/video2pr path/to/meeting.mp4
```

Output goes to `.video2pr/<video-name>/` (add `.video2pr/` to your `.gitignore`). `source.json` records recording path, size, and modification time. For a different or changed recording with the same basename, choose a different output directory. Legacy outputs without provenance require explicit confirmation before reuse.

## What It Does

1. Extracts audio from video (mp4, mkv, avi, mov, webm)
2. Detects spoken language with confidence scoring - asks for confirmation if < 80%
3. Transcribes via Whisper with word-level timestamps, or imports an external transcript (Google Meet SBV/TXT, MS Teams VTT/DOCX, Zoom VTT/TXT) with speaker attribution
4. Analyzes the codebase against what was discussed and produces a concrete implementation plan (`plan.md`)
5. Produces `summary.md` with topics, action items, decisions, visual reference commands, and a link to the implementation plan
6. Optionally creates GitHub Issues from plan tasks (each confirmed individually before creation)

If a transcript file sits next to the video (same name, `.sbv`/`.vtt`/`.txt`/`.docx` extension), it's picked up automatically. Zoom, Google Meet, and MS Teams formats are auto-detected. Speaker-prefixed TXT and untimed DOCX imports are preserved in `external_transcript.json` for enrichment after Whisper supplies timestamps. TXT/DOCX end times may be estimated; metadata distinguishes observed starts from unknown timing. Unrecognized imports fail without replacing prior transcripts. Untimed imports are stored separately; a prior timestamped transcript survives until Whisper successfully publishes its replacement.

## Whisper Model Choices

The `--model` flag controls the quality/speed tradeoff for transcription:

| Model | Parameters | Relative Speed | Best For |
|-------|-----------|----------------|----------|
| `base` | 74M | ~10x realtime | Quick drafts, testing, short meetings |
| `small` | 244M | ~4x realtime | **Default** - good balance of speed and accuracy |
| `medium` | 769M | ~1.5x realtime | Important meetings where accuracy matters |
| `large-v3` | 1550M | ~0.5x realtime | Maximum accuracy, multilingual content |
| `turbo` | 809M | ~3x realtime | Fast with good accuracy (faster-whisper only) |

Speed estimates depend on hardware, model, language, and decoding settings; treat them as rough guidance. The skill reports GPU diagnostics and relevant setup guidance when acceleration is unavailable. On Windows, CUDA is considered ready only after a tiny real inference smoke test succeeds; `nvidia-smi`, imports, and CTranslate2 supported compute types alone are not enough.

## Standalone Scripts

```bash
# Detect language
conda run -n video2pr python scripts/transcribe.py --input audio.wav --detect-language

# Transcribe with explicit language and device selection
conda run -n video2pr python scripts/transcribe.py --input audio.wav --output-dir out --model small --language en --device auto

# Convert an external transcript
conda run -n video2pr python scripts/convert_transcript.py --input meeting.vtt --output-dir out
```

## Troubleshooting

<details>
<summary><code>conda: command not found</code></summary>

The skill runs everything via `conda run -n video2pr`. If the assistant reports `conda` is missing, install Miniconda or Anaconda and ensure it's on your `PATH`. On Windows + Git Bash, the dependency check (`scripts/check_deps.py`) also probes common install locations under `%USERPROFILE%\miniconda3\` and `C:\ProgramData\` automatically — so a fresh install should usually be picked up without re-launching the shell.

</details>

<details>
<summary><code>ffmpeg: command not found</code> on Windows</summary>

`ffmpeg` is provided by the `video2pr` conda env, not your system. Run commands via `conda run -n video2pr ...` or activate the env. If `conda env create -f environment.yml` succeeded but ffmpeg is still missing, your conda install may have failed to write to PATH — re-create the env or run `conda activate video2pr && which ffmpeg` to confirm.

</details>

<details>
<summary>Wrong language was auto-detected</summary>

The skill detects language with the `base` model and reports a confidence score. If confidence is below 80%, it asks you to confirm before transcribing. If you got past that prompt and the result is wrong, re-run with an explicit language code:

```bash
conda run -n video2pr python scripts/transcribe.py \
  --input audio.wav --output-dir out --model small --language pt
```

Use the ISO 639-1 code (`en`, `pt`, `es`, `fr`, `de`, `ja`, ...). The skill will then re-transcribe end-to-end.

</details>

<details>
<summary>Transcription appears to hang</summary>

CPU processing time varies with hardware and decoding settings. Progress appears after the first completed segment, then at most every five seconds as more segments complete. CUDA worker stderr streams during processing. Model downloads and model loading precede segment progress. To go faster, install GPU acceleration (see next section) or switch to `--model base` for a quick draft.

</details>

<details>
<summary>"GPU detected but CTranslate2 is CPU-only"</summary>

A hardware query or compute-type failure alone cannot establish whether a CTranslate2 build is CPU-only. Inspect the failure stage and diagnostics: import errors, driver/runtime problems, model downloads, and actual inference failures need different repairs. CUDA execution also requires compatible cuBLAS and cuDNN libraries; upgrading CTranslate2 alone does not install those libraries. Follow the platform-specific [faster-whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu), then rerun `conda run -n video2pr python scripts/check_gpu.py`.

</details>

<details>
<summary>CUDA is detected but transcription crashes or falls back to CPU on Windows</summary>

Some CUDA failures happen inside CTranslate2's native runtime before Python can print a traceback. `scripts/check_gpu.py` now runs a tiny CUDA inference smoke test and reports CUDA as usable only when inference succeeds.

If `--device cuda` fails, the script prints the child process exit code, package versions, CTranslate2 compute types, `nvidia-smi` details, and Windows PATH/DLL hints. If `--device auto` sees the same CUDA failure, it warns and retries on CPU so the transcription can continue.

Common causes are incompatible or shadowed CUDA/cuDNN/cuBLAS DLLs, a CTranslate2 wheel/runtime mismatch, GPU memory pressure from another transcription, or an input-dependent native CTranslate2 failure. Keep using `--device auto` unless you specifically want CUDA failures to stop the run.

</details>

<details>
<summary>I edited a <code>SKILL.md</code> and my changes got overwritten</summary>

The three `SKILL.md` files under `.claude/`, `.agents/`, and `.github/` are generated from `skill/SKILL.md` (see "Editing the skill prompt" above). Edit the canonical source and run `python scripts/sync_skill.py`.

</details>

## Output Files

| File | Description |
|------|-------------|
| `audio.wav` | 16kHz mono audio |
| `metadata.json` | ffprobe video metadata |
| `source.json` | Recording identity for safe reuse |
| `transcript.json` | Segments with timestamps, text, optional speaker/word data |
| `transcript.srt` | SRT subtitles (Whisper-generated only) |
| `plan.md` | Codebase-grounded implementation plan with prioritized tasks |
| `progress.md` | Task completion tracker (persists across runs) |
| `summary.md` | Structured meeting analysis with implementation plan summary |
| `external_transcript_meta.json` | Source format and timing provenance |
| `external_transcript.json` | Preserved parsed import for speaker enrichment |
| `external_transcript_original.*` | Copy of original transcript (external only) |


## Development and validation

Package and interpreter versions in `environment.yml` are intentionally unconstrained. Setup should select the latest mutually compatible releases for the current platform and verify them with an inference smoke test. If a dependency fails, inspect current upstream compatibility guidance and adjust the local environment without adding repository pins. Helpers are tested on Python 3.12, 3.13, and 3.14; CPU integration tests run on Windows and Linux with Python 3.13 as a test target, not an installation requirement. GPU behavior has mocked failure-path tests and a separate opt-in hardware smoke check.

```bash
python -m pytest -q --ignore=tests/test_e2e_pipeline.py
conda run -n video2pr python -m pytest -q tests/test_e2e_pipeline.py
ruff check .
ruff format --check .
python scripts/sync_skill.py --check
```

Integration fixtures use FFV1 video and PCM audio, avoiding optional H.264 encoders. A synthetic speech fixture exercises nonempty text and word timestamps without requiring exact recognition. Issue linkage and implementation completion are tracked separately, with persistent task IDs across reruns.

Install development tools with `python -m pip install ruff pre-commit`. Ruff is installed without a version constraint in CI; local pre-commit hooks use the Ruff installed in the developer environment. Normalized PCM audio is read directly, and other standalone media is decoded by the required FFmpeg CLI, so transcription does not depend on PyAV container-open keyword compatibility.
