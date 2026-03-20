# video2PR

Converts meeting video recordings into structured context for coding assistants. Extracts audio, transcribes with timestamps, detects language, and produces a structured summary with topics, action items, decisions, and visual references.

## Features

- **Audio extraction** — Extracts 16kHz mono WAV from video files (mp4, mkv, avi, mov, webm)
- **Language detection** — Identifies spoken language with confidence scoring before transcription
- **Whisper transcription** — Word-level timestamps with automatic chunking for long recordings
- **External transcript support** — Imports Google Meet (SBV, TXT) and MS Teams (VTT, DOCX) transcripts with speaker attribution
- **Structured summary** — Topics, action items, decisions, feature requests, and visual references with timestamps
- **On-demand frame extraction** — Pull specific video frames when visual context is needed

## Setup

```bash
conda env create -f environment.yml
conda activate video2pr
```

## Usage

Use the Claude Code skill to process a recording:

```
/analyze-video path/to/meeting.mp4
```

The skill will:
1. Check dependencies
2. Validate the video and search for external transcripts in the same directory
3. Extract audio and detect language (asks for confirmation if confidence < 80%)
4. Transcribe using Whisper or convert the external transcript
5. Analyze and generate a structured summary

Output is saved to `.video2pr/<video-name>/`.

### External Transcripts

If a transcript file is found alongside the video (matching basename with `.sbv`, `.vtt`, `.txt`, or `.docx` extension), it will be used automatically. External transcripts preserve speaker attribution that Whisper alone cannot provide.

### Standalone Scripts

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
| `transcript.json` | Segments with timestamps, text, and optional speaker/word data |
| `transcript.srt` | SRT subtitles (Whisper-generated only) |
| `summary.md` | Structured meeting analysis |
| `external_transcript_meta.json` | Source format info (external transcript only) |
| `external_transcript_original.*` | Copy of original transcript (external only) |

## Project Structure

```
video2PR/
├── CLAUDE.md                          # Project instructions for Claude Code
├── environment.yml                    # Conda environment definition
├── .claude/skills/analyze-video/
│   ├── SKILL.md                       # Skill phases and orchestration
│   └── scripts/
│       ├── check_deps.py              # Dependency checker
│       ├── extract_audio.py           # Audio extraction + metadata
│       ├── extract_frame.py           # On-demand frame extraction
│       ├── convert_transcript.py      # External transcript parser
│       └── transcribe.py             # Whisper transcription + language detection
└── .video2pr/                         # Runtime output (gitignored)
```
