from __future__ import annotations

import argparse
import sys
from pathlib import Path

from epuboverlay.synthesizers import create_synthesizer
from epuboverlay.pipeline import generate_media_overlay_epub
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

    # Validate synthesizer parameters
    if parsed.synthesizer == "f5-tts":
        if not parsed.ref_audio or not parsed.ref_text:
            print("Error: --ref-audio and --ref-text are required when using the f5-tts synthesizer.",
                  file=sys.stderr)
            return 1
    elif parsed.synthesizer == "pocket-tts":
        if not parsed.ref_audio:
            print("Error: --ref-audio is required when using the pocket-tts synthesizer.",
                  file=sys.stderr)
            return 1
    elif parsed.synthesizer == "kokoro":
        if not parsed.voice and not parsed.voice_formula:
            print("Error: Either --voice or --voice-formula must be specified when using the kokoro synthesizer.",
                  file=sys.stderr)
            return 1

    try:
        synth_config = vars(parsed)
        # Match expected dict keys for create_synthesizer factory
        synth_config["ref_audio_path"] = parsed.ref_audio
        synthesizer = create_synthesizer(parsed.synthesizer, **synth_config)
    except Exception as e:
        print(f"Error initializing synthesizer: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    print("Orchestrating EPUB Media Overlay generation...")
    print(f"Input EPUB: {parsed.epub}")
    print(f"Output EPUB: {parsed.output_epub}")
    print(f"Synthesizer: {parsed.synthesizer}")
    print(f"Concurrency: {parsed.concurrency}")
    print()

    reporter = ConsoleProgressReporter()

    # Load normalization settings from settings.json
    import json
    settings_path = Path.home() / ".epuboverlay" / "settings.json"
    norm_settings = {
        "expand_numerals": True,
        "resolve_contractions": True,
        "resolve_heteronyms": True,
        "harmonize_punctuation": True,
        "custom_lexicon": [],
    }
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                current = saved.get("current_settings", {})
                for k in norm_settings:
                    if k in current:
                        norm_settings[k] = current[k]
        except Exception:
            pass

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
            normalization_settings=norm_settings,
        )
        print("\nSuccess! Synced EPUB generated successfully.")
        return 0
    except Exception as e:
        import traceback
        print(f"\nOrchestration failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


def _cmd_extract(parsed: argparse.Namespace) -> int:
    """Execute the 'extract' subcommand — extract Audio and Subtitles from EPUB3."""
    from epuboverlay.extract import epub_to_audio_subtitles

    epub_path = parsed.epub.expanduser()
    output_dir = parsed.output.expanduser()

    print(f"Extracting Audio + Subtitles from: {epub_path}")
    print(f"Output directory: {output_dir}")
    if parsed.merge:
        print("Mode: Merged (single Audio + Subtitle set)")
    else:
        print("Mode: Per-chapter (separate Audio + Subtitles per chapter)")
    
    # Parse formats
    formats_list = [f.strip().lower() for f in parsed.formats.split(",") if f.strip()]
    print(f"Target formats: {', '.join(formats_list)}")
    print()

    def progress_cb(msg: str) -> None:
        print(msg)

    try:
        results = epub_to_audio_subtitles(
            epub_path=epub_path,
            output_dir=output_dir,
            merge=parsed.merge,
            formats=formats_list,
            progress_callback=progress_cb,
        )
        print(f"\n✓ Extracted {len(results)} set(s):")
        for audio, subtitles in results:
            sub_names = ", ".join(s.name for s in subtitles)
            print(f"  • {audio.name}  +  [{sub_names}]")
        return 0
    except Exception as e:
        import traceback
        print(f"\nExtraction failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="epuboverlay — EPUB 3 Media Overlay tools with F5-TTS, Kokoro, and Pocket-TTS.",
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
        choices=["f5-tts", "kokoro", "pocket-tts", "dummy"],
        default="f5-tts",
        help="Synthesizer implementation to use (default: f5-tts)."
    )
    gen_parser.add_argument(
        "-a", "--ref-audio",
        type=Path,
        help="Path to the reference audio clip (required for f5-tts and pocket-tts)."
    )
    gen_parser.add_argument(
        "-t", "--ref-text",
        type=str,
        help="Transcript text of the reference audio clip (required for f5-tts)."
    )
    gen_parser.add_argument(
        "--voice",
        type=str,
        default="",
        help="Name of Kokoro voice to use (e.g. af_heart)."
    )
    gen_parser.add_argument(
        "--voice-formula",
        type=str,
        default="",
        help="Custom voice mix formula for Kokoro (e.g. af_heart*0.6+af_sky*0.4)."
    )
    gen_parser.add_argument(
        "--lang-code",
        type=str,
        default="a",
        help="Language code for Kokoro synthesizer (default: 'a')."
    )
    gen_parser.add_argument(
        "--compile",
        action="store_true",
        default=False,
        help="Compile model (torch.compile) to optimize inference speed (f5-tts only)."
    )
    gen_parser.add_argument(
        "--device",
        type=str,
        help="Compute device for inference (e.g. cuda, cpu, mps)."
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
        help="Extract audio tracks and subtitle files from an EPUB3 with Media Overlays.",
        description="Extract audio tracks and subtitle files (ASS, SRT, VTT, TTML, SBV, LRC, TXT) from an EPUB3 with Media Overlays.",
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
        help="Output directory for extracted audio and subtitle files."
    )
    ext_parser.add_argument(
        "--merge",
        action="store_true",
        default=False,
        help="Merge all chapters into a single audio + subtitle set."
    )
    ext_parser.add_argument(
        "--formats",
        default="ass",
        help="Comma-separated list of subtitle formats to export (choices: ass, srt, vtt, ttml, sbv, lrc, txt; default: ass)."
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
