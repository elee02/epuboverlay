import tempfile
import unittest
import zipfile
from pathlib import Path

from epuboverlay.pipeline import (
    TextChunk,
    TimestampedLine,
    extract_spine_text_chunks,
    format_lrc,
    synthesize_with_internal_timestamps,
)


class DummySynthesizer:
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
        synth = DummySynthesizer([100, 50])

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


if __name__ == "__main__":
    unittest.main()
