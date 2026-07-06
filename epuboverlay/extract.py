"""Extract MP3 + LRC files from an EPUB3 with Media Overlays."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable


@dataclass
class ChapterOverlay:
    """Parsed chapter overlay data from an EPUB3 file."""
    idref: str
    title: str
    xhtml_href: str
    smil_href: str
    audio_href: str  # path inside the ZIP
    # List of (element_id, clip_begin_secs, clip_end_secs)
    timings: list[tuple[str, float, float]] = field(default_factory=list)
    # Map element_id -> text content
    id_to_text: dict[str, str] = field(default_factory=dict)


class _IDTextExtractor(HTMLParser):
    """Extract text content from elements with id attributes in XHTML."""
    def __init__(self) -> None:
        super().__init__()
        self._id_stack: list[str | None] = []
        self._current_id: str | None = None
        self._results: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        elem_id = attr_dict.get("id")
        self._id_stack.append(elem_id)
        if elem_id:
            self._current_id = elem_id
            if elem_id not in self._results:
                self._results[elem_id] = []

    def handle_endtag(self, tag: str) -> None:
        if self._id_stack:
            popped = self._id_stack.pop()
            if popped == self._current_id:
                # Find the innermost active id
                self._current_id = None
                for stacked_id in reversed(self._id_stack):
                    if stacked_id:
                        self._current_id = stacked_id
                        break

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped and self._current_id and self._current_id in self._results:
            self._results[self._current_id].append(stripped)

    def get_id_texts(self) -> dict[str, str]:
        return {
            eid: " ".join(parts).strip()
            for eid, parts in self._results.items()
            if parts
        }


def _parse_smil_time(time_str: str) -> float:
    """Parse SMIL time values like '1.234s', '00:01:02.345', or plain '1.234'."""
    time_str = time_str.strip()
    if time_str.endswith("ms"):
        return float(time_str[:-2]) / 1000.0
    if time_str.endswith("s"):
        return float(time_str[:-1])
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
    return float(time_str)


def parse_epub_overlays(epub_path: str | Path) -> list[ChapterOverlay]:
    """Parse an EPUB3 file and extract chapter overlay data.

    Returns a list of ChapterOverlay objects, one per spine item that has
    a media-overlay attribute linking to a SMIL file.
    """
    epub_path = Path(epub_path)
    chapters: list[ChapterOverlay] = []

    with zipfile.ZipFile(epub_path, "r") as zf:
        # Find OPF
        container_xml = zf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
        rootfile = container_root.find(".//{*}rootfile")
        if rootfile is None:
            raise ValueError("EPUB container is missing a rootfile entry")
        opf_path = rootfile.attrib.get("full-path", "")
        if not opf_path:
            raise ValueError("EPUB rootfile entry is missing full-path")

        opf_root = ET.fromstring(zf.read(opf_path))
        opf_dir = Path(opf_path).parent

        # Build manifest map: id -> {href, media-type, media-overlay}
        manifest_items: dict[str, dict[str, str]] = {}
        for item in opf_root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib.get("id", "")
            if item_id:
                manifest_items[item_id] = {
                    "href": item.attrib.get("href", ""),
                    "media-type": item.attrib.get("media-type", ""),
                    "media-overlay": item.attrib.get("media-overlay", ""),
                }

        # Get book title for fallback naming
        title_el = opf_root.find(".//{*}title")
        book_title = title_el.text.strip() if title_el is not None and title_el.text else epub_path.stem

        # Walk spine
        spine_itemrefs = opf_root.findall(".//{*}spine/{*}itemref")
        chapter_idx = 0

        for itemref in spine_itemrefs:
            idref = itemref.attrib.get("idref", "")
            item_data = manifest_items.get(idref)
            if not item_data:
                continue
            if item_data["media-type"] != "application/xhtml+xml":
                continue

            overlay_id = item_data.get("media-overlay", "")
            if not overlay_id:
                continue

            smil_data = manifest_items.get(overlay_id)
            if not smil_data or smil_data["media-type"] != "application/smil+xml":
                continue

            chapter_idx += 1

            # Resolve paths relative to OPF directory
            xhtml_href = item_data["href"]
            smil_href = smil_data["href"]

            xhtml_zip_path = _normalize_zip_path(opf_dir, xhtml_href)
            smil_zip_path = _normalize_zip_path(opf_dir, smil_href)

            # Parse SMIL to get timings and audio reference
            try:
                smil_content = zf.read(smil_zip_path)
            except KeyError:
                continue

            smil_root = ET.fromstring(smil_content)
            timings: list[tuple[str, float, float]] = []
            audio_href = ""

            for par in smil_root.findall(".//{*}par"):
                text_el = par.find("{*}text")
                audio_el = par.find("{*}audio")
                if text_el is None or audio_el is None:
                    continue

                text_src = text_el.attrib.get("src", "")
                # Extract element ID from fragment: "chapter.xhtml#span-id"
                element_id = ""
                if "#" in text_src:
                    element_id = text_src.split("#", 1)[1]

                clip_begin = _parse_smil_time(audio_el.attrib.get("clipBegin", "0"))
                clip_end = _parse_smil_time(audio_el.attrib.get("clipEnd", "0"))

                if element_id:
                    timings.append((element_id, clip_begin, clip_end))

                if not audio_href:
                    audio_src = audio_el.attrib.get("src", "")
                    if audio_src:
                        # Resolve audio path relative to SMIL file location
                        smil_dir = Path(smil_zip_path).parent
                        audio_href = _normalize_zip_path(smil_dir, audio_src)

            if not timings or not audio_href:
                continue

            # Parse XHTML to extract text for each element ID
            try:
                xhtml_content = zf.read(xhtml_zip_path).decode("utf-8", errors="ignore")
            except KeyError:
                continue

            extractor = _IDTextExtractor()
            extractor.feed(xhtml_content)
            id_to_text = extractor.get_id_texts()

            chapter = ChapterOverlay(
                idref=idref,
                title=f"Chapter {chapter_idx}",
                xhtml_href=xhtml_href,
                smil_href=smil_href,
                audio_href=audio_href,
                timings=timings,
                id_to_text=id_to_text,
            )
            chapters.append(chapter)

    return chapters


def _normalize_zip_path(base_dir: Path, href: str) -> str:
    """Normalize a path relative to a base directory for ZIP lookups."""
    combined = (base_dir / href).as_posix()
    normalized = os.path.normpath(combined)
    # Remove leading ./ or /
    normalized = normalized.lstrip("./")
    return normalized


def build_lrc_from_chapter(chapter: ChapterOverlay) -> str:
    """Build LRC lyrics content from a chapter's SMIL timings and text.

    Args:
        chapter: A parsed ChapterOverlay with timings and id_to_text.

    Returns:
        LRC formatted string.
    """
    lines: list[str] = []
    for element_id, clip_begin, _clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        total_seconds = max(clip_begin, 0.0)
        minutes = int(total_seconds // 60)
        seconds = total_seconds - (minutes * 60)
        lines.append(f"[{minutes:02d}:{seconds:05.2f}] {text}")
    return "\n".join(lines)


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name or "chapter"


def epub_to_mp3_lrc(
    epub_path: str | Path,
    output_dir: str | Path,
    merge: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> list[tuple[Path, Path]]:
    """Extract MP3 + LRC file pairs from an EPUB3 with Media Overlays.

    Args:
        epub_path: Path to the input EPUB3 file.
        output_dir: Directory to write output files.
        merge: If True, merge all chapters into a single MP3+LRC pair.
        progress_callback: Optional callback for status messages.

    Returns:
        List of (mp3_path, lrc_path) tuples for each output file.
    """
    epub_path = Path(epub_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    _log(f"Parsing EPUB overlays from: {epub_path.name}")
    chapters = parse_epub_overlays(epub_path)

    if not chapters:
        raise ValueError(
            "No chapters with media overlays found. "
            "The EPUB may not have audio overlays embedded."
        )

    _log(f"Found {len(chapters)} chapters with media overlays")

    # Extract book title from EPUB metadata
    book_title = epub_path.stem
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            container_xml = zf.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is not None:
                opf_path = rootfile.attrib.get("full-path", "")
                if opf_path:
                    opf_root = ET.fromstring(zf.read(opf_path))
                    title_el = opf_root.find(".//{*}title")
                    if title_el is not None and title_el.text:
                        book_title = title_el.text.strip()
    except Exception:
        pass

    # Extract per-chapter audio + LRC
    chapter_outputs: list[tuple[Path, Path]] = []
    with zipfile.ZipFile(epub_path, "r") as zf:
        for idx, chapter in enumerate(chapters):
            _log(f"Extracting chapter {idx + 1}/{len(chapters)}: {chapter.idref}")

            # Generate safe filename
            chapter_name = _sanitize_filename(f"{idx + 1:02d}_{chapter.idref}")

            # Detect audio format from the source href extension
            audio_ext = Path(chapter.audio_href).suffix or ".mp3"

            # Extract audio
            audio_out = output_dir / f"{chapter_name}{audio_ext}"
            try:
                audio_data = zf.read(chapter.audio_href)
                audio_out.write_bytes(audio_data)
            except KeyError:
                _log(f"  Warning: audio file not found in EPUB: {chapter.audio_href}")
                continue

            # Build LRC
            lrc_content = build_lrc_from_chapter(chapter)
            lrc_out = output_dir / f"{chapter_name}.lrc"
            lrc_out.write_text(lrc_content, encoding="utf-8")

            chapter_outputs.append((audio_out, lrc_out))
            _log(f"  ✓ {audio_out.name} + {lrc_out.name}")

    if not chapter_outputs:
        raise ValueError("No audio files could be extracted from the EPUB.")

    if not merge:
        _log(f"Done! Extracted {len(chapter_outputs)} chapter(s) to {output_dir}")
        return chapter_outputs

    # Merge all chapters into a single audio + LRC
    _log("Merging all chapters into a single audio+LRC pair...")

    # Detect audio format from the first chapter's source
    audio_ext = Path(chapters[0].audio_href).suffix or ".mp3"

    merged_name = _sanitize_filename(book_title)
    merged_audio = output_dir / f"{merged_name}{audio_ext}"
    merged_lrc = output_dir / f"{merged_name}.lrc"

    # Concatenate audio files using ffmpeg
    audio_paths = [audio for audio, _lrc in chapter_outputs]
    _merge_audio_files(audio_paths, merged_audio)

    # Build merged LRC with adjusted timestamps
    merged_lrc_lines: list[str] = []
    time_offset = 0.0

    for chapter in chapters:
        chapter_lrc_lines = build_lrc_from_chapter(chapter).splitlines()
        if not chapter_lrc_lines:
            continue

        if time_offset > 0:
            # Adjust timestamps by adding the offset
            for line in chapter_lrc_lines:
                match = re.match(r'\[(\d+):(\d+\.\d+)\]\s*(.*)', line)
                if match:
                    minutes = int(match.group(1))
                    seconds = float(match.group(2))
                    text = match.group(3)
                    total = minutes * 60 + seconds + time_offset
                    new_min = int(total // 60)
                    new_sec = total - (new_min * 60)
                    merged_lrc_lines.append(f"[{new_min:02d}:{new_sec:05.2f}] {text}")
                else:
                    merged_lrc_lines.append(line)
        else:
            merged_lrc_lines.extend(chapter_lrc_lines)

        # Get chapter duration from last timing
        if chapter.timings:
            _elem_id, _begin, last_end = chapter.timings[-1]
            time_offset += last_end

    merged_lrc.write_text("\n".join(merged_lrc_lines), encoding="utf-8")

    # Clean up per-chapter files
    for audio, lrc in chapter_outputs:
        audio.unlink(missing_ok=True)
        lrc.unlink(missing_ok=True)

    _log(f"Done! Merged output: {merged_audio.name} + {merged_lrc.name}")
    return [(merged_audio, merged_lrc)]


def _merge_audio_files(audio_paths: list[Path], output_path: Path) -> None:
    """Concatenate multiple audio files using ffmpeg's concat demuxer."""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        shutil.copy2(audio_paths[0], output_path)
        return

    # Create a concat list file for ffmpeg
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as list_file:
        for audio in audio_paths:
            # Escape single quotes in paths for ffmpeg
            escaped = str(audio.resolve()).replace("'", "'\\''")
            list_file.write(f"file '{escaped}'\n")
        list_file_path = list_file.name

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file_path,
            "-codec", "copy",
            str(output_path),
        ]
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg merge failed: {stderr}") from e
    finally:
        os.unlink(list_file_path)
