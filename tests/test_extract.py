"""Tests for EPUB3 → MP3+LRC extraction."""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


class ExtractTests(unittest.TestCase):
    """Test the extract module functions."""

    def _make_wav_bytes(self, duration: float = 0.5, sample_rate: int = 24000) -> bytes:
        """Create minimal WAV bytes with silence."""
        num_samples = int(duration * sample_rate)
        pcm_data = b"\x00" * (num_samples * 2)
        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(sample_rate)
            wav_out.writeframes(pcm_data)
        return out_io.getvalue()

    def _make_test_epub_with_overlays(self, epub_path: Path) -> None:
        """Create a minimal EPUB3 with media overlays for testing."""
        with zipfile.ZipFile(epub_path, "w") as zf:
            # mimetype
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

            # container.xml
            zf.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")

            # content.opf
            zf.writestr("OEBPS/content.opf", """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"
         prefix="media: http://www.idpf.org/2007/ops#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="uid">test-123</dc:identifier>
    <meta property="media:duration">00:00:01.500</meta>
    <meta property="media:duration" refines="#smil_ch1">00:00:01.000</meta>
    <meta property="media:duration" refines="#smil_ch2">00:00:00.500</meta>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml" media-overlay="smil_ch1"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml" media-overlay="smil_ch2"/>
    <item id="smil_ch1" href="smil_ch1.smil" media-type="application/smil+xml"/>
    <item id="smil_ch2" href="smil_ch2.smil" media-type="application/smil+xml"/>
    <item id="audio_ch1" href="audio/audio_ch1.wav" media-type="audio/wav"/>
    <item id="audio_ch2" href="audio/audio_ch2.wav" media-type="audio/wav"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>""")

            # Chapter 1 XHTML
            zf.writestr("OEBPS/ch1.xhtml", """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
  <p id="p1">Hello world.</p>
  <p id="p2">This is chapter one.</p>
</body>
</html>""")

            # Chapter 2 XHTML
            zf.writestr("OEBPS/ch2.xhtml", """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
  <p id="p3">Chapter two begins here.</p>
</body>
</html>""")

            # SMIL for Chapter 1
            zf.writestr("OEBPS/smil_ch1.smil", """<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq epub:textref="ch1.xhtml">
      <par id="par_p1">
        <text src="ch1.xhtml#p1"/>
        <audio src="audio/audio_ch1.wav" clipBegin="0.000s" clipEnd="0.500s"/>
      </par>
      <par id="par_p2">
        <text src="ch1.xhtml#p2"/>
        <audio src="audio/audio_ch1.wav" clipBegin="0.500s" clipEnd="1.000s"/>
      </par>
    </seq>
  </body>
</smil>""")

            # SMIL for Chapter 2
            zf.writestr("OEBPS/smil_ch2.smil", """<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq epub:textref="ch2.xhtml">
      <par id="par_p3">
        <text src="ch2.xhtml#p3"/>
        <audio src="audio/audio_ch2.wav" clipBegin="0.000s" clipEnd="0.500s"/>
      </par>
    </seq>
  </body>
</smil>""")

            # Audio files (use WAV bytes since we don't need real MP3 for parsing tests)
            wav_bytes = self._make_wav_bytes(1.0)
            zf.writestr("OEBPS/audio/audio_ch1.wav", wav_bytes)
            wav_bytes2 = self._make_wav_bytes(0.5)
            zf.writestr("OEBPS/audio/audio_ch2.wav", wav_bytes2)

    def test_parse_epub_overlays(self) -> None:
        """Test that parse_epub_overlays correctly extracts chapter overlay data."""
        from epuboverlay.extract import parse_epub_overlays

        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "test.epub"
            self._make_test_epub_with_overlays(epub_path)

            chapters = parse_epub_overlays(epub_path)

            self.assertEqual(len(chapters), 2)

            # Chapter 1
            ch1 = chapters[0]
            self.assertEqual(ch1.idref, "ch1")
            self.assertEqual(len(ch1.timings), 2)
            self.assertEqual(ch1.timings[0][0], "p1")  # element ID
            self.assertAlmostEqual(ch1.timings[0][1], 0.0)  # clipBegin
            self.assertAlmostEqual(ch1.timings[0][2], 0.5)  # clipEnd
            self.assertEqual(ch1.timings[1][0], "p2")
            self.assertAlmostEqual(ch1.timings[1][1], 0.5)
            self.assertAlmostEqual(ch1.timings[1][2], 1.0)
            self.assertEqual(ch1.id_to_text.get("p1"), "Hello world.")
            self.assertEqual(ch1.id_to_text.get("p2"), "This is chapter one.")

            # Chapter 2
            ch2 = chapters[1]
            self.assertEqual(ch2.idref, "ch2")
            self.assertEqual(len(ch2.timings), 1)
            self.assertEqual(ch2.timings[0][0], "p3")
            self.assertEqual(ch2.id_to_text.get("p3"), "Chapter two begins here.")

    def test_build_lrc_from_chapter(self) -> None:
        """Test LRC generation from chapter overlay data."""
        from epuboverlay.extract import ChapterOverlay, build_lrc_from_chapter

        chapter = ChapterOverlay(
            idref="ch1",
            title="Chapter 1",
            xhtml_href="ch1.xhtml",
            smil_href="smil_ch1.smil",
            audio_href="audio/audio_ch1.mp3",
            timings=[
                ("p1", 0.0, 0.5),
                ("p2", 0.5, 1.0),
                ("p3", 65.25, 70.0),
            ],
            id_to_text={
                "p1": "Hello world.",
                "p2": "This is chapter one.",
                "p3": "A line after a minute.",
            },
        )

        lrc = build_lrc_from_chapter(chapter)
        lines = lrc.splitlines()

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "[00:00.00] Hello world.")
        self.assertEqual(lines[1], "[00:00.50] This is chapter one.")
        self.assertEqual(lines[2], "[01:05.25] A line after a minute.")

    def test_build_lrc_skips_missing_text(self) -> None:
        """Test that LRC generation skips entries with no matching text."""
        from epuboverlay.extract import ChapterOverlay, build_lrc_from_chapter

        chapter = ChapterOverlay(
            idref="ch1",
            title="Chapter 1",
            xhtml_href="ch1.xhtml",
            smil_href="smil_ch1.smil",
            audio_href="audio/audio_ch1.mp3",
            timings=[
                ("p1", 0.0, 0.5),
                ("missing_id", 0.5, 1.0),
            ],
            id_to_text={"p1": "Only this line."},
        )

        lrc = build_lrc_from_chapter(chapter)
        lines = lrc.splitlines()

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "[00:00.00] Only this line.")

    def test_parse_smil_time(self) -> None:
        """Test SMIL time value parsing."""
        from epuboverlay.extract import _parse_smil_time

        # Seconds with 's' suffix
        self.assertAlmostEqual(_parse_smil_time("1.234s"), 1.234)
        self.assertAlmostEqual(_parse_smil_time("0s"), 0.0)

        # Milliseconds with 'ms' suffix
        self.assertAlmostEqual(_parse_smil_time("1500ms"), 1.5)

        # HH:MM:SS format
        self.assertAlmostEqual(_parse_smil_time("01:02:03.5"), 3723.5)

        # MM:SS format
        self.assertAlmostEqual(_parse_smil_time("02:30.5"), 150.5)

        # Plain number
        self.assertAlmostEqual(_parse_smil_time("42.5"), 42.5)

    def test_epub_to_mp3_lrc_per_chapter(self) -> None:
        """Test full extraction producing per-chapter output."""
        from epuboverlay.extract import epub_to_mp3_lrc

        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "test.epub"
            output_dir = Path(tmpdir) / "output"
            self._make_test_epub_with_overlays(epub_path)

            log_messages = []
            results = epub_to_mp3_lrc(
                epub_path=epub_path,
                output_dir=output_dir,
                merge=False,
                progress_callback=lambda msg: log_messages.append(msg),
            )

            self.assertEqual(len(results), 2)

            # Check files exist
            for mp3, lrc in results:
                self.assertTrue(mp3.exists(), f"MP3 not found: {mp3}")
                self.assertTrue(lrc.exists(), f"LRC not found: {lrc}")
                self.assertGreater(mp3.stat().st_size, 0)
                self.assertGreater(lrc.stat().st_size, 0)

            # Check LRC content
            lrc_content = results[0][1].read_text(encoding="utf-8")
            self.assertIn("Hello world.", lrc_content)
            self.assertIn("This is chapter one.", lrc_content)

            lrc_content2 = results[1][1].read_text(encoding="utf-8")
            self.assertIn("Chapter two begins here.", lrc_content2)

            # Check progress was reported
            self.assertTrue(any("Parsing" in msg for msg in log_messages))
            self.assertTrue(any("Extracting" in msg for msg in log_messages))

    def test_epub_to_mp3_lrc_no_overlays(self) -> None:
        """Test that extraction raises ValueError for EPUBs without overlays."""
        from epuboverlay.extract import epub_to_mp3_lrc

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal EPUB without overlays
            epub_path = Path(tmpdir) / "no_overlay.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
                zf.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
                zf.writestr("content.opf", """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>No Overlays</dc:title>
    <dc:identifier id="uid">test-456</dc:identifier>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>""")
                zf.writestr("ch1.xhtml", """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello</p></body></html>""")

            output_dir = Path(tmpdir) / "output"
            with self.assertRaises(ValueError) as ctx:
                epub_to_mp3_lrc(epub_path=epub_path, output_dir=output_dir)
            self.assertIn("No chapters with media overlays", str(ctx.exception))

    def test_round_trip_generate_then_extract(self) -> None:
        """Test round-trip: generate EPUB with overlays, then extract MP3+LRC."""
        from epuboverlay.pipeline import generate_media_overlay_epub
        from epuboverlay.synthesizers import DummySynthesizer
        from epuboverlay.extract import epub_to_mp3_lrc

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a source EPUB
            input_epub = tmpdir / "input.epub"
            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
                zf.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
                zf.writestr("content.opf", """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Round Trip Test</dc:title>
    <dc:identifier id="uid">rt-001</dc:identifier>
  </metadata>
  <manifest>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>""")
                zf.writestr("chap1.xhtml", """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
  <p>The quick brown fox jumped over the lazy dog.</p>
  <p>And then it ran away into the forest.</p>
</body>
</html>""")

            # Generate overlays
            output_epub = tmpdir / "output.epub"
            cache_dir = tmpdir / "cache"
            synth = DummySynthesizer(sample_rate=24000)

            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=24000.0,
                max_chars=150,
                cache_dir=cache_dir,
            )

            self.assertTrue(output_epub.exists())

            # Now extract MP3+LRC from the generated EPUB
            extract_dir = tmpdir / "extracted"
            results = epub_to_mp3_lrc(
                epub_path=output_epub,
                output_dir=extract_dir,
                merge=False,
            )

            # Should have at least one chapter
            self.assertGreater(len(results), 0)

            for mp3, lrc in results:
                self.assertTrue(mp3.exists())
                self.assertTrue(lrc.exists())

                lrc_text = lrc.read_text(encoding="utf-8")
                # LRC should contain timestamps
                self.assertRegex(lrc_text, r'\[\d+:\d+\.\d+\]')
                # LRC should contain actual text from the EPUB
                self.assertTrue(
                    "fox" in lrc_text.lower() or "dog" in lrc_text.lower() or "forest" in lrc_text.lower(),
                    f"Expected EPUB text in LRC but got:\n{lrc_text}"
                )

    def test_sanitize_filename(self) -> None:
        """Test filename sanitization."""
        from epuboverlay.extract import _sanitize_filename

        self.assertEqual(_sanitize_filename("chapter_1"), "chapter_1")
        self.assertEqual(_sanitize_filename('a<b>c:d"e'), "a_b_c_d_e")
        self.assertEqual(_sanitize_filename(""), "chapter")
        self.assertEqual(_sanitize_filename("..."), "chapter")

    def test_normalize_zip_path(self) -> None:
        """Test ZIP path normalization."""
        from epuboverlay.extract import _normalize_zip_path

        self.assertEqual(_normalize_zip_path(Path("OEBPS"), "ch1.xhtml"), "OEBPS/ch1.xhtml")
        self.assertEqual(_normalize_zip_path(Path("OEBPS"), "../ch1.xhtml"), "ch1.xhtml")
        self.assertEqual(_normalize_zip_path(Path("."), "ch1.xhtml"), "ch1.xhtml")

    def test_format_timestamps(self) -> None:
        """Test timestamp formatting functions."""
        from epuboverlay.extract import format_timestamp, format_ass_timestamp, format_sbv_timestamp

        # Standard timestamp (comma for SRT, dot for VTT)
        self.assertEqual(format_timestamp(0.0, ","), "00:00:00,000")
        self.assertEqual(format_timestamp(61.237, ","), "00:01:01,237")
        self.assertEqual(format_timestamp(3665.999, "."), "01:01:05.999")
        
        # ASS timestamp (H:MM:SS.cs)
        self.assertEqual(format_ass_timestamp(0.0), "0:00:00.00")
        self.assertEqual(format_ass_timestamp(61.237), "0:01:01.24")
        self.assertEqual(format_ass_timestamp(3665.999), "1:01:06.00")
        
        # SBV timestamp (H:MM:SS.mmm)
        self.assertEqual(format_sbv_timestamp(0.0), "0:00:00.000")
        self.assertEqual(format_sbv_timestamp(61.237), "0:01:01.237")
        self.assertEqual(format_sbv_timestamp(3665.999), "1:01:05.999")

    def test_epub_to_audio_subtitles_all_formats(self) -> None:
        """Test extraction of audio and all 7 subtitle formats."""
        from epuboverlay.extract import epub_to_audio_subtitles

        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "test.epub"
            output_dir = Path(tmpdir) / "output"
            self._make_test_epub_with_overlays(epub_path)

            formats = ["ass", "srt", "vtt", "ttml", "sbv", "lrc", "txt"]
            results = epub_to_audio_subtitles(
                epub_path=epub_path,
                output_dir=output_dir,
                merge=False,
                formats=formats,
            )

            self.assertEqual(len(results), 2)
            for audio, subtitles in results:
                self.assertTrue(audio.exists())
                self.assertEqual(len(subtitles), 7)
                for sub in subtitles:
                    self.assertTrue(sub.exists())
                    self.assertGreater(sub.stat().st_size, 0)
                    
                # Verify specific contents
                extensions = {sub.suffix for sub in subtitles}
                self.assertEqual(extensions, {".ass", ".srt", ".vtt", ".ttml", ".sbv", ".lrc", ".txt"})

    def test_epub_to_audio_subtitles_merged(self) -> None:
        """Test merged extraction for all formats."""
        from epuboverlay.extract import epub_to_audio_subtitles

        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "test.epub"
            output_dir = Path(tmpdir) / "output"
            self._make_test_epub_with_overlays(epub_path)

            formats = ["ass", "srt", "vtt", "ttml", "sbv", "lrc", "txt"]
            results = epub_to_audio_subtitles(
                epub_path=epub_path,
                output_dir=output_dir,
                merge=True,
                formats=formats,
            )

            self.assertEqual(len(results), 1)
            audio, subtitles = results[0]
            self.assertTrue(audio.exists())
            self.assertEqual(len(subtitles), 7)
            
            # Check content of merged ASS
            ass_path = next(p for p in subtitles if p.suffix == ".ass")
            ass_text = ass_path.read_text(encoding="utf-8")
            self.assertIn("Dialogue:", ass_text)
            self.assertIn("Hello world.", ass_text)
            self.assertIn("Chapter two begins here.", ass_text)



class StreamingWavTests(unittest.TestCase):
    """Test the new disk-streaming WAV helper functions."""

    def _make_wav_bytes(self, num_samples: int = 1000, sample_rate: int = 24000) -> bytes:
        """Create WAV bytes with silence."""
        pcm_data = b"\x00" * (num_samples * 2)
        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(sample_rate)
            wav_out.writeframes(pcm_data)
        return out_io.getvalue()

    def test_write_chunk_to_tempfile(self) -> None:
        """Test writing WAV bytes to a temp file."""
        from epuboverlay.pipeline import write_chunk_to_tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_bytes = self._make_wav_bytes(500)
            chunk_path, frame_count = write_chunk_to_tempfile(wav_bytes, Path(tmpdir), 0)

            self.assertTrue(chunk_path.exists())
            self.assertEqual(chunk_path.name, "chunk_000000.wav")
            self.assertEqual(frame_count, 500)

            # Verify the file is valid WAV
            with wave.open(str(chunk_path), "rb") as wav_in:
                self.assertEqual(wav_in.getnframes(), 500)

    def test_stream_concat_wav_to_file(self) -> None:
        """Test streaming concatenation of WAV files."""
        from epuboverlay.pipeline import write_chunk_to_tempfile, stream_concat_wav_to_file

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            chunk_paths = []

            # Create 3 chunk files
            for i in range(3):
                wav_bytes = self._make_wav_bytes(100 * (i + 1))
                chunk_path, _ = write_chunk_to_tempfile(wav_bytes, tmpdir, i)
                chunk_paths.append(chunk_path)

            # Concatenate
            output_path = tmpdir / "merged.wav"
            stream_concat_wav_to_file(chunk_paths, output_path)

            self.assertTrue(output_path.exists())

            # Verify total frame count = 100 + 200 + 300
            with wave.open(str(output_path), "rb") as wav_in:
                self.assertEqual(wav_in.getnframes(), 600)

    def test_stream_concat_wav_empty(self) -> None:
        """Test streaming concatenation with no inputs."""
        from epuboverlay.pipeline import stream_concat_wav_to_file

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "merged.wav"
            stream_concat_wav_to_file([], output_path)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
