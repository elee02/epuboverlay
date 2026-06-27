from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Protocol
import xml.etree.ElementTree as ET
import zipfile


@dataclass(frozen=True)
class TextChunk:
    text: str


@dataclass(frozen=True)
class TimestampedLine:
    start_seconds: float
    text: str


class FrameTimedSynthesizer(Protocol):
    """Synthesizer that exposes output frame lengths per generated chunk."""

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Return encoded audio bytes and generated frame count for the chunk."""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def text(self) -> str:
        return " ".join(self._parts).strip()


def extract_spine_text_chunks(epub_path: str | Path) -> list[TextChunk]:
    """Extract readable spine content from an EPUB as ordered text chunks."""
    epub_path = Path(epub_path)
    with zipfile.ZipFile(epub_path) as zf:
        container_xml = zf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
        rootfile = container_root.find(".//{*}rootfile")
        if rootfile is None:
            raise ValueError("EPUB container is missing a rootfile entry")

        opf_path = rootfile.attrib.get("full-path")
        if not opf_path:
            raise ValueError("EPUB rootfile entry is missing full-path")

        opf_root = ET.fromstring(zf.read(opf_path))

        manifest: dict[str, str] = {}
        for item in opf_root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib.get("id")
            href = item.attrib.get("href")
            if item_id and href:
                manifest[item_id] = href

        base_dir = Path(opf_path).parent
        chunks: list[TextChunk] = []
        for itemref in opf_root.findall(".//{*}spine/{*}itemref"):
            idref = itemref.attrib.get("idref")
            href = manifest.get(idref or "")
            if not href:
                continue

            html_path = str((base_dir / href).as_posix())
            extractor = _HTMLTextExtractor()
            extractor.feed(zf.read(html_path).decode("utf-8", errors="ignore"))
            text = extractor.text()
            if text:
                chunks.append(TextChunk(text=text))

    return chunks


def synthesize_with_internal_timestamps(
    chunks: Iterable[TextChunk],
    synthesizer: FrameTimedSynthesizer,
    frame_rate_hz: float,
) -> tuple[list[bytes], list[TimestampedLine]]:
    """Generate chunk audio and derive timestamps directly from generated frame counts."""
    if frame_rate_hz <= 0:
        raise ValueError("frame_rate_hz must be positive")

    current_frames = 0
    audio_chunks: list[bytes] = []
    timestamped_lines: list[TimestampedLine] = []

    for chunk in chunks:
        audio, generated_frames = synthesizer.synthesize(chunk.text)
        if generated_frames < 0:
            raise ValueError("generated frame count cannot be negative")

        timestamped_lines.append(
            TimestampedLine(start_seconds=current_frames / frame_rate_hz, text=chunk.text)
        )
        audio_chunks.append(audio)
        current_frames += generated_frames

    return audio_chunks, timestamped_lines


def format_lrc(lines: Iterable[TimestampedLine]) -> str:
    formatted: list[str] = []
    for line in lines:
        total_seconds = max(line.start_seconds, 0.0)
        minutes = int(total_seconds // 60)
        seconds = total_seconds - (minutes * 60)
        formatted.append(f"[{minutes:02d}:{seconds:05.2f}] {line.text}")

    return "\n".join(formatted)
