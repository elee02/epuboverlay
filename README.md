# epuboverlay

Generate standard, narrated **EPUB 3 files with Media Overlays** using F5-TTS voice cloning. 

Instead of generating clunky, standalone `.lrc` files, this tool modifies the EPUB itself: it segments the XHTML text into sentences, wraps them in visual tags, synthesizes spoken audio in your own cloned voice, compresses it using `ffmpeg`, and generates standard SMIL multimedia sync maps. 

This enables standard e-book readers (like Apple Books, Kobo, or Thorium Reader) to highlight sentences or paragraphs in sync as the narrated audio plays.

## Features
- 🚀 **AI Voice Cloning**: Zero-shot voice cloning using F5-TTS.
- 📊 **CLI Live Progress**: Visual chapter/chunk progress bar, elapsed time, and ETA.
- 🖥️ **Web Dashboard**: Premium dark-mode SPA to upload files, configure jobs, monitor progress, play live audio previews of finished chapters, and download final EPUBs.

## Prerequisites

- **Python:** 3.8+
- **System Tool:** `ffmpeg` (required to compress synthesized WAV files into MP3)
  ```bash
  # Debian/Ubuntu
  sudo apt install ffmpeg
  # macOS
  brew install ffmpeg
  ```
- **TTS Library:** `f5-tts` (only required if running the F5-TTS voice cloning model; the dummy mode requires no deep-learning dependencies)

## Installation

1. Clone the repository and navigate into it:
   ```bash
   git clone <repo-url>
   cd epuboverlay
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install package dependencies:
   ```bash
   # Basic (installs web dashboard and dummy synthesizer dependencies)
   pip install -e .
   
   # With F5-TTS Voice Cloning support
   pip install f5-tts
   ```

## Usage

### 1. Web Dashboard (Recommended)

Start the local web dashboard using the console script:
```bash
epuboverlay-web --port 8765
```
Open `http://localhost:8765` in your browser. You can upload an EPUB, customize parameters, view live progress graphs, preview completed chapters, and download your finished book.

### 2. Command Line Interface (CLI)

Run the CLI using python module syntax:
```bash
# Zero-Shot Voice Cloning (F5-TTS Mode)
python -m epuboverlay \
  --epub path/to/input.epub \
  -o path/to/output_synced.epub \
  --synthesizer f5-tts \
  --ref-audio path/to/your_voice.wav \
  --ref-text "This is a transcript of my short voice clip." \
  --device cuda

# Dummy / Testing Mode (instant overlays with silent audio)
python -m epuboverlay \
  --epub path/to/input.epub \
  -o path/to/output_synced.epub \
  --synthesizer dummy
```

Running the CLI displays a live progress indicator:
```text
[Chapter 1/2] [Chunk 2/3] |███░░░░░░░░░░░░░░░░░| 16.7% Elapsed: 0m25.4s ETA: ~2m05.0s
```

## CLI Configuration Options

| Option | Shortcut | Description | Default |
|---|---|---|---|
| `--epub` | | **[Required]** Path to the input EPUB file | |
| `--output-epub` | `-o` | **[Required]** Path to save the generated narrated EPUB | |
| `--synthesizer` | `-s` | Synthesizer implementation (`f5-tts` or `dummy`) | `f5-tts` |
| `--ref-audio` | `-a` | Path to reference voice clip (Required for F5-TTS) | |
| `--ref-text` | `-t` | Transcript of the reference voice clip (Required for F5-TTS) | |
| `--device` | | Compute device for F5-TTS (`cuda`, `cpu`, `mps`) | `None` (auto) |
| `--speed` | | Speech generation speed multiplier | `1.0` |
| `--max-chars` | | Maximum character limit per sentence segment | `150` |
| `--frame-rate` | | Audio sampling rate in Hz | `24000.0` |

## Testing

Run unit tests:
```bash
python -m unittest discover -v
```
