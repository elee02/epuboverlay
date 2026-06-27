import io
import tempfile
import unittest
import wave
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from epuboverlay.pipeline import (
    TextChunk,
    TimestampedLine,
    DummySynthesizer,
    extract_spine_text_chunks,
    format_lrc,
    synthesize_with_internal_timestamps,
    replace_html_entities,
    split_into_sentences,
    chunk_text,
    generate_smil_content,
    concatenate_wavs,
    generate_media_overlay_epub,
)


class DummyFrameSynthesizer:
    def __init__(self, frame_counts: list[int]) -> None:
        self._frame_counts = frame_counts
        self._index = 0

    def synthesize(self, text: str) -> tuple[bytes, int]:
        count = self._frame_counts[self._index]
        self._index += 1
        return text.encode("utf-8"), count


class PipelineTests(unittest.TestCase):
    def test_internal_timestamps_are_accumulated_from_frames(self) -> None:
        chunks = [TextChunk("Hello"), TextChunk("World")]
        synth = DummyFrameSynthesizer([100, 50])

        audio_chunks, lines = synthesize_with_internal_timestamps(
            chunks, synth, frame_rate_hz=100
        )

        self.assertEqual(audio_chunks, [b"Hello", b"World"])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(lines[0].start_seconds, 0.0)
        self.assertAlmostEqual(lines[1].start_seconds, 1.0)

    def test_format_lrc_uses_minutes_seconds_hundredths(self) -> None:
        content = format_lrc(
            [
                TimestampedLine(start_seconds=0.0, text="start"),
                TimestampedLine(start_seconds=61.237, text="later"),
            ]
        )
        self.assertEqual(content.splitlines(), ["[00:00.00] start", "[01:01.24] later"])

    def test_extract_spine_text_chunks_reads_ordered_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "sample.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                        <item id='c2' href='chapter2.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                        <itemref idref='c2'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><h1>One</h1><p>First chapter.</p></body></html>",
                )
                zf.writestr(
                    "OEBPS/chapter2.xhtml",
                    "<html><body><h1>Two</h1><p>Second chapter.</p></body></html>",
                )

            chunks = extract_spine_text_chunks(epub_path)
            self.assertEqual([c.text for c in chunks], ["One First chapter.", "Two Second chapter."])

    def test_replace_html_entities(self) -> None:
        self.assertEqual(
            replace_html_entities("Hello &nbsp; world &ldquo; test &rdquo; &amp; &lt;"),
            "Hello &#160; world &#8220; test &#8221; &amp; &lt;"
        )

    def test_split_into_sentences(self) -> None:
        text = "Mr. Smith went to the store. He bought milk. Dr. Jones was there, too!"
        sentences = split_into_sentences(text)
        self.assertEqual(
            sentences,
            [
                "Mr. Smith went to the store.",
                "He bought milk.",
                "Dr. Jones was there, too!"
            ]
        )

    def test_chunk_text(self) -> None:
        text = "This is a sentence. And this is a very long sentence that has some clauses, which will split it, and more words."
        chunks = chunk_text(text, max_chars=40)
        # Ensure none of the chunks exceed 40 characters
        for c in chunks:
            self.assertTrue(len(c) <= 40, f"Chunk too long: {c}")

    def test_generate_smil_content(self) -> None:
        mappings = [
            ("s1", 0.0, 1.5),
            ("s2", 1.5, 3.75)
        ]
        smil = generate_smil_content("chapter1.xhtml", mappings, "audio/chapter1.mp3")
        self.assertIn('<text src="chapter1.xhtml#s1"/>', smil)
        self.assertIn('<audio src="audio/chapter1.mp3" clipBegin="1.500s" clipEnd="3.750s"/>', smil)

    def test_concatenate_wavs(self) -> None:
        out1 = io.BytesIO()
        with wave.open(out1, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00" * 100)
        wav1 = out1.getvalue()

        out2 = io.BytesIO()
        with wave.open(out2, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x11" * 100)
        wav2 = out2.getvalue()

        merged = concatenate_wavs([wav1, wav2])
        merged_io = io.BytesIO(merged)
        with wave.open(merged_io, "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), 8000)
            self.assertEqual(w.getnframes(), 100)

    def test_generate_media_overlay_epub(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_epub = Path(tmpdir) / "sample.epub"
            output_epub = Path(tmpdir) / "synced.epub"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr(
                    "mimetype",
                    "application/epub+zip",
                )
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Test Book</dc:title>
                      </metadata>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello world. This is a synced book test.</p></body></html>",
                )

            synth = DummySynthesizer(sample_rate=8000)
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
            )

            self.assertTrue(output_epub.exists())

            with zipfile.ZipFile(output_epub, "r") as zf:
                files = zf.namelist()
                self.assertIn("OEBPS/chapter1.xhtml", files)
                self.assertIn("OEBPS/smil_c1.smil", files)
                self.assertIn("OEBPS/audio/audio_c1.mp3", files)

                opf_data = zf.read("OEBPS/content.opf")
                opf_root = ET.fromstring(opf_data)

                manifest = opf_root.find(".//{*}manifest")
                items = manifest.findall(".//{*}item")
                media_overlays = [i.attrib.get("media-overlay") for i in items if i.attrib.get("id") == "c1"]
                self.assertEqual(media_overlays, ["smil_c1"])

                metadata = opf_root.find(".//{*}metadata")
                metas = metadata.findall(".//{*}meta")
                durations = [m.text for m in metas if m.attrib.get("property") == "media:duration"]
                self.assertEqual(len(durations), 2)
                refined_durations = [m.text for m in metas if m.attrib.get("refines") == "#smil_c1"]
                self.assertEqual(len(refined_durations), 1)

    def test_progress_events_are_emitted(self) -> None:
        from epuboverlay.progress import ProgressEvent

        with tempfile.TemporaryDirectory() as tmpdir:
            input_epub = Path(tmpdir) / "sample.epub"
            output_epub = Path(tmpdir) / "synced.epub"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Test Book</dc:title>
                      </metadata>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello world.</p></body></html>",
                )

            events = []
            def progress_cb(event: ProgressEvent):
                events.append(event)

            synth = DummySynthesizer(sample_rate=8000)
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
                progress_callback=progress_cb,
            )

            self.assertTrue(len(events) > 0)
            phases = [e.phase for e in events]
            self.assertIn("parsing", phases)
            self.assertIn("synthesizing", phases)
            self.assertIn("converting", phases)
            self.assertIn("packaging", phases)
            self.assertIn("done", phases)

    def test_checkpointing_resumes_and_skips_processing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_epub = Path(tmpdir) / "sample.epub"
            output_epub1 = Path(tmpdir) / "synced1.epub"
            output_epub2 = Path(tmpdir) / "synced2.epub"
            cache_dir = Path(tmpdir) / "cache"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Test Book</dc:title>
                      </metadata>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                        <item id='c2' href='chapter2.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                        <itemref idref='c2'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello chapter one.</p></body></html>",
                )
                zf.writestr(
                    "OEBPS/chapter2.xhtml",
                    "<html><body><p>Hello chapter two.</p></body></html>",
                )

            # First run: run with a tracking synthesizer to verify it gets called
            class TrackingSynthesizer:
                def __init__(self):
                    self.synthesize_calls = []
                def synthesize(self, text: str) -> tuple[bytes, int]:
                    self.synthesize_calls.append(text)
                    # Return mock WAV (silence)
                    out_io = io.BytesIO()
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(1)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(8000)
                        wav_out.writeframes(b"\x00" * 1600)  # 0.2 seconds
                    return out_io.getvalue(), 1600

            synth1 = TrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub1,
                synthesizer=synth1,
                frame_rate_hz=8000.0,
                cache_dir=cache_dir,
            )

            # Verify both chapters were synthesized
            self.assertEqual(len(synth1.synthesize_calls), 2)
            self.assertIn("Hello chapter one.", synth1.synthesize_calls)
            self.assertIn("Hello chapter two.", synth1.synthesize_calls)

            # Second run: run with same cache dir but a new tracking synthesizer
            synth2 = TrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub2,
                synthesizer=synth2,
                frame_rate_hz=8000.0,
                cache_dir=cache_dir,
            )

            # Verify synthesizer was NOT called because they are cached
            self.assertEqual(len(synth2.synthesize_calls), 0)
            self.assertTrue(output_epub2.exists())


if __name__ == "__main__":
    sys.exit(unittest.main())
