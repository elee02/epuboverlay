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


def _cmd_generate(parsed: argparse.Namespace) -> int:
    """Execute the 'generate' subcommand — EPUB Media Overlay generation."""
    import os
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    try:
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except Exception:
        pass

    # Expand tildes in paths
    parsed.epub = parsed.epub.expanduser()
    parsed.output_epub = parsed.output_epub.expanduser()
    if parsed.ref_audio:
        parsed.ref_audio = parsed.ref_audio.expanduser()
    if parsed.cache_dir:
        parsed.cache_dir = parsed.cache_dir.expanduser()

    if parsed.synthesizer == "f5-tts":
        if not parsed.ref_audio or not parsed.ref_text:
            print("Error: --ref-audio and --ref-text are required when using the f5-tts synthesizer.",
                  file=sys.stderr)
            return 1

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
    print(f"Concurrency: {parsed.concurrency}")
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
            concurrency=parsed.concurrency,
        )
        print("\nSuccess! Synced EPUB generated successfully.")
        return 0
    except Exception as e:
        import traceback
        print(f"\nOrchestration failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


def _cmd_extract(parsed: argparse.Namespace) -> int:
    """Execute the 'extract' subcommand — extract MP3+LRC from EPUB3."""
    from epuboverlay.extract import epub_to_mp3_lrc

    epub_path = parsed.epub.expanduser()
    output_dir = parsed.output.expanduser()

    print(f"Extracting MP3+LRC from: {epub_path}")
    print(f"Output directory: {output_dir}")
    if parsed.merge:
        print("Mode: Merged (single MP3+LRC pair)")
    else:
        print("Mode: Per-chapter (separate MP3+LRC per chapter)")
    print()

    def progress_cb(msg: str) -> None:
        print(msg)

    try:
        results = epub_to_mp3_lrc(
            epub_path=epub_path,
            output_dir=output_dir,
            merge=parsed.merge,
            progress_callback=progress_cb,
        )
        print(f"\n✓ Extracted {len(results)} file pair(s):")
        for mp3, lrc in results:
            print(f"  • {mp3.name}  +  {lrc.name}")
        return 0
    except Exception as e:
        import traceback
        print(f"\nExtraction failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="epuboverlay — EPUB 3 Media Overlay tools with AI Voice Cloning.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── generate subcommand ──
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate EPUB 3 Media Overlays using F5-TTS or a dummy synthesizer.",
        description="Generate standard EPUB 3 Media Overlays using F5-TTS or a dummy synthesizer.",
    )
    gen_parser.add_argument(
        "--epub",
        required=True,
        type=Path,
        help="Path to the input EPUB file."
    )
    gen_parser.add_argument(
        "-o", "--output-epub",
        required=True,
        type=Path,
        help="Path to save the generated synced EPUB file."
    )
    gen_parser.add_argument(
        "-s", "--synthesizer",
        choices=["f5-tts", "dummy"],
        default="f5-tts",
        help="Synthesizer implementation to use (default: f5-tts)."
    )
    gen_parser.add_argument(
        "-a", "--ref-audio",
        type=Path,
        help="Path to the reference audio clip (required if using f5-tts)."
    )
    gen_parser.add_argument(
        "-t", "--ref-text",
        type=str,
        help="Transcript text of the reference audio clip (required if using f5-tts)."
    )
    gen_parser.add_argument(
        "--device",
        type=str,
        help="Compute device for F5-TTS inference (e.g. cuda, cpu, mps)."
    )
    gen_parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed factor (default: 1.0)."
    )
    gen_parser.add_argument(
        "--max-chars",
        type=int,
        default=150,
        help="Maximum characters per chunk of synthesis (default: 150)."
    )
    gen_parser.add_argument(
        "--frame-rate",
        type=float,
        default=24000.0,
        help="Synthesizer output frame rate or audio sample rate in Hz (default: 24000.0)."
    )
    gen_parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Custom directory to cache intermediate files and skip already processed chapters."
    )
    gen_parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=2,
        help="Number of concurrent workers for synthesis (default: 2)."
    )

    # ── extract subcommand ──
    ext_parser = subparsers.add_parser(
        "extract",
        help="Extract MP3 + LRC files from an EPUB3 with Media Overlays.",
        description="Extract MP3 + LRC files from an EPUB3 with Media Overlays for playback on music players like Poweramp.",
    )
    ext_parser.add_argument(
        "--epub",
        required=True,
        type=Path,
        help="Path to the input EPUB3 file with media overlays."
    )
    ext_parser.add_argument(
        "-o", "--output",
        required=True,
        type=Path,
        help="Output directory for MP3 + LRC files."
    )
    ext_parser.add_argument(
        "--merge",
        action="store_true",
        default=False,
        help="Merge all chapters into a single MP3 + LRC pair."
    )

    parsed = parser.parse_args(args)

    if parsed.command is None:
        parser.print_help()
        return 0

    if parsed.command == "generate":
        return _cmd_generate(parsed)
    elif parsed.command == "extract":
        return _cmd_extract(parsed)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
