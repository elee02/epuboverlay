from __future__ import annotations

import argparse
import sys
from pathlib import Path

from epuboverlay.pipeline import (
    DummySynthesizer,
    F5TTSSynthesizer,
    generate_media_overlay_epub,
)
from epuboverlay.progress import ConsoleProgressReporter


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate standard EPUB 3 Media Overlays using F5-TTS or a dummy synthesizer."
    )
    parser.add_argument(
        "--epub",
        required=True,
        type=Path,
        help="Path to the input EPUB file."
    )
    parser.add_argument(
        "-o", "--output-epub",
        required=True,
        type=Path,
        help="Path to save the generated synced EPUB file."
    )
    parser.add_argument(
        "-s", "--synthesizer",
        choices=["f5-tts", "dummy"],
        default="f5-tts",
        help="Synthesizer implementation to use (default: f5-tts)."
    )
    parser.add_argument(
        "-a", "--ref-audio",
        type=Path,
        help="Path to the reference audio clip (required if using f5-tts)."
    )
    parser.add_argument(
        "-t", "--ref-text",
        type=str,
        help="Transcript text of the reference audio clip (required if using f5-tts)."
    )
    parser.add_argument(
        "--device",
        type=str,
        help="Compute device for F5-TTS inference (e.g. cuda, cpu, mps)."
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed factor (default: 1.0)."
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=150,
        help="Maximum characters per chunk of synthesis (default: 150)."
    )
    parser.add_argument(
        "--frame-rate",
        type=float,
        default=24000.0,
        help="Synthesizer output frame rate or audio sample rate in Hz (default: 24000.0)."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Custom directory to cache intermediate files and skip already processed chapters."
    )

    parsed = parser.parse_args(args)

    # Expand tildes in paths
    parsed.epub = parsed.epub.expanduser()
    parsed.output_epub = parsed.output_epub.expanduser()
    if parsed.ref_audio:
        parsed.ref_audio = parsed.ref_audio.expanduser()
    if parsed.cache_dir:
        parsed.cache_dir = parsed.cache_dir.expanduser()

    if parsed.synthesizer == "f5-tts":
        if not parsed.ref_audio or not parsed.ref_text:
            parser.error("--ref-audio and --ref-text are required when using the f5-tts synthesizer.")

        try:
            synthesizer = F5TTSSynthesizer(
                ref_audio=parsed.ref_audio,
                ref_text=parsed.ref_text,
                device=parsed.device,
                speed=parsed.speed,
            )
        except Exception as e:
            print(f"Error initializing F5-TTS synthesizer: {e}", file=sys.stderr)
            return 1
    else:
        synthesizer = DummySynthesizer(sample_rate=int(parsed.frame_rate))

    print("Orchestrating EPUB Media Overlay generation...")
    print(f"Input EPUB: {parsed.epub}")
    print(f"Output EPUB: {parsed.output_epub}")
    print(f"Synthesizer: {parsed.synthesizer}")
    print()

    reporter = ConsoleProgressReporter()

    try:
        generate_media_overlay_epub(
            input_epub=parsed.epub,
            output_epub=parsed.output_epub,
            synthesizer=synthesizer,
            frame_rate_hz=parsed.frame_rate,
            max_chars=parsed.max_chars,
            progress_callback=reporter.report,
            cache_dir=parsed.cache_dir,
        )
        print("\nSuccess! Synced EPUB generated successfully.")
        return 0
    except Exception as e:
        import traceback
        print(f"\nOrchestration failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

