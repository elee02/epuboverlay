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
from epuboverlay.pipeline import parse_epub_toc


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
    """Extract text content from elements with id attributes in XHTML, plus title/headings."""
    def __init__(self) -> None:
        super().__init__()
        self._id_stack: list[str | None] = []
        self._current_id: str | None = None
        self._results: dict[str, list[str]] = {}
        self._current_tag: str | None = None
        self._title: str | None = None
        self._heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        attr_dict = dict(attrs)
        elem_id = attr_dict.get("id")
        self._id_stack.append(elem_id)
        if elem_id:
            self._current_id = elem_id
            if elem_id not in self._results:
                self._results[elem_id] = []

    def handle_endtag(self, tag: str) -> None:
        if self._current_tag == tag.lower():
            self._current_tag = None
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
        if stripped:
            if self._current_id and self._current_id in self._results:
                self._results[self._current_id].append(stripped)
            if self._current_tag == "title" and not self._title:
                self._title = stripped
            elif self._current_tag in ("h1", "h2") and not self._heading:
                self._heading = stripped

    def get_id_texts(self) -> dict[str, str]:
        return {
            eid: " ".join(parts).strip()
            for eid, parts in self._results.items()
            if parts
        }

    def get_title(self) -> str:
        if self._heading:
            return self._heading
        if self._title:
            return self._title
        return ""


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

        # Build TOC map
        toc_map = parse_epub_toc(zf, opf_path, opf_root)

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

            # Retrieve clean title from TOC, falling back to html headers or Chapter X
            normalized_xhtml_path = os.path.normpath(xhtml_zip_path).replace("\\", "/").lstrip("./").lstrip("/")
            extracted_title = toc_map.get(normalized_xhtml_path)
            if not extracted_title:
                extracted_title = extractor.get_title().strip()
            
            chapter_title = extracted_title if extracted_title else f"Chapter {chapter_idx}"

            chapter = ChapterOverlay(
                idref=idref,
                title=chapter_title,
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


def _get_audio_duration(path: Path) -> float:
    """Get duration of audio file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return float(result.stdout.decode().strip())
    except Exception:
        return 0.0


def _escape_metadata(val: str) -> str:
    """Escape FFmpeg metadata special characters."""
    return val.replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', '\\\n')


def _extract_epub_cover(epub_path: Path, output_image_path: Path) -> bool:
    """Attempt to find and extract the cover art image from the EPUB file.

    Returns True if successful, False otherwise.
    """
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            container_xml = zf.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                return False
            opf_path = rootfile.attrib.get("full-path", "")
            if not opf_path:
                return False
            
            opf_content = zf.read(opf_path)
            opf_root = ET.fromstring(opf_content)
            opf_dir = Path(opf_path).parent

            # 1. Look for item with property="cover-image"
            cover_href = ""
            for item in opf_root.findall(".//{*}manifest/{*}item"):
                properties = item.attrib.get("properties", "")
                if "cover-image" in properties:
                    cover_href = item.attrib.get("href", "")
                    break

            # 2. Look for legacy meta cover tag
            if not cover_href:
                for meta in opf_root.findall(".//{*}metadata/{*}meta"):
                    if meta.attrib.get("name") == "cover":
                        cover_id = meta.attrib.get("content")
                        if cover_id:
                            # find item with this id
                            for item in opf_root.findall(".//{*}manifest/{*}item"):
                                if item.attrib.get("id") == cover_id:
                                    cover_href = item.attrib.get("href", "")
                                    break
                            if cover_href:
                                break

            # 3. Fallback: search for item with id containing "cover"
            if not cover_href:
                for item in opf_root.findall(".//{*}manifest/{*}item"):
                    item_id = item.attrib.get("id", "").lower()
                    if "cover" in item_id and item.attrib.get("media-type", "").startswith("image/"):
                        cover_href = item.attrib.get("href", "")
                        break

            if cover_href:
                cover_zip_path = _normalize_zip_path(opf_dir, cover_href)
                img_data = zf.read(cover_zip_path)
                output_image_path.write_bytes(img_data)
                return True
    except Exception:
        pass
    return False


def _process_cover_art(img_path: Path, output_path: Path) -> Path:
    """Ensures the cover image is a high-resolution 1400x1400 JPEG if PIL is available."""
    try:
        from PIL import Image
        with Image.open(img_path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            resized = img.resize((1400, 1400), Image.Resampling.LANCZOS)
            resized.save(output_path, "JPEG", quality=90)
            return output_path
    except Exception:
        if img_path != output_path:
            shutil.copy2(img_path, output_path)
        return output_path


def _convert_to_m4b(
    input_audio: Path,
    output_path: Path,
    metadata: dict[str, str],
    chapters: list[ChapterOverlay] | None = None,
    chapter_durations: list[float] | None = None,
    cover_art: Path | None = None,
) -> None:
    """Convert input audio to a proper M4B audiobook file with metadata, chapters, and cover art."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as meta_file:
        meta_file.write(";FFMETADATA1\n")
        for k, v in metadata.items():
            if v:
                meta_file.write(f"{k}={_escape_metadata(v)}\n")
        
        if chapters and chapter_durations:
            current_ms = 0
            for idx, ch in enumerate(chapters):
                if idx < len(chapter_durations):
                    dur_ms = int(round(chapter_durations[idx] * 1000))
                    meta_file.write("[CHAPTER]\n")
                    meta_file.write("TIMEBASE=1/1000\n")
                    meta_file.write(f"START={current_ms}\n")
                    end_ms = current_ms + dur_ms
                    meta_file.write(f"END={end_ms}\n")
                    meta_file.write(f"title={_escape_metadata(ch.title)}\n")
                    current_ms = end_ms
        meta_file_path = Path(meta_file.name)

    try:
        is_aac = False
        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_audio)
            ]
            codec = subprocess.run(probe_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
            if codec == "aac":
                is_aac = True
        except Exception:
            pass

        cmd = ["ffmpeg", "-y"]
        cmd.extend(["-i", str(input_audio)])
        
        if cover_art and cover_art.exists():
            cmd.extend(["-i", str(cover_art)])
            
        cmd.extend(["-i", str(meta_file_path)])
        
        if cover_art and cover_art.exists():
            cmd.extend([
                "-map", "0:a",
                "-map", "1:v",
                "-map_metadata", "2",
            ])
        else:
            cmd.extend([
                "-map", "0:a",
                "-map_metadata", "1",
            ])

        if is_aac:
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "64k"])

        if cover_art and cover_art.exists():
            cmd.extend([
                "-c:v", "mjpeg",
                "-disposition:v:1", "attached_pic"
            ])

        cmd.extend(["-movflags", "+faststart"])
        cmd.extend(["-f", "mp4"])
        cmd.extend([str(output_path)])

        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"FFmpeg M4B generation failed: {stderr}") from e
    finally:
        meta_file_path.unlink(missing_ok=True)


def _convert_to_m4a(
    input_audio: Path,
    output_path: Path,
    metadata: dict[str, str],
    cover_art: Path | None = None,
) -> None:
    """Convert input audio to an M4A file with metadata and cover art (no chapter markers).

    Produces a standard AAC-in-MP4 container (.m4a) using the 'ipod' format atom
    for maximum compatibility with music players like Poweramp and iTunes.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as meta_file:
        meta_file.write(";FFMETADATA1\n")
        for k, v in metadata.items():
            if v:
                meta_file.write(f"{k}={_escape_metadata(v)}\n")
        meta_file_path = Path(meta_file.name)

    try:
        is_aac = False
        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_audio)
            ]
            codec = subprocess.run(probe_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
            if codec == "aac":
                is_aac = True
        except Exception:
            pass

        cmd = ["ffmpeg", "-y"]
        cmd.extend(["-i", str(input_audio)])

        if cover_art and cover_art.exists():
            cmd.extend(["-i", str(cover_art)])

        cmd.extend(["-i", str(meta_file_path)])

        if cover_art and cover_art.exists():
            cmd.extend([
                "-map", "0:a",
                "-map", "1:v",
                "-map_metadata", "2",
            ])
        else:
            cmd.extend([
                "-map", "0:a",
                "-map_metadata", "1",
            ])

        if is_aac:
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "64k"])

        if cover_art and cover_art.exists():
            cmd.extend([
                "-c:v", "mjpeg",
                "-disposition:v:1", "attached_pic"
            ])

        cmd.extend(["-movflags", "+faststart"])
        cmd.extend(["-f", "mp4"])
        cmd.extend([str(output_path)])

        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"FFmpeg M4A generation failed: {stderr}") from e
    finally:
        meta_file_path.unlink(missing_ok=True)


def format_timestamp(seconds: float, decimal_sep: str = ",") -> str:
    """Format seconds into HH:MM:SS[sep]mmm."""
    total_seconds = max(seconds, 0.0)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    ms = int(round((total_seconds - int(total_seconds)) * 1000))
    if ms >= 1000:
        secs += 1
        ms -= 1000
        if secs >= 60:
            secs -= 60
            minutes += 1
            if minutes >= 60:
                minutes -= 60
                hours += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_sep}{ms:03d}"


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into H:MM:SS.cs (centiseconds)."""
    total_seconds = max(seconds, 0.0)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    cs = int(round((total_seconds - int(total_seconds)) * 100))
    if cs >= 100:
        secs += 1
        cs -= 100
        if secs >= 60:
            secs -= 60
            minutes += 1
            if minutes >= 60:
                minutes -= 60
                hours += 1
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def format_sbv_timestamp(seconds: float) -> str:
    """Format seconds into H:MM:SS.mmm."""
    total_seconds = max(seconds, 0.0)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    ms = int(round((total_seconds - int(total_seconds)) * 1000))
    if ms >= 1000:
        secs += 1
        ms -= 1000
        if secs >= 60:
            secs -= 60
            minutes += 1
            if minutes >= 60:
                minutes -= 60
                hours += 1
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_lrc_from_chapter(chapter: ChapterOverlay, time_offset: float = 0.0) -> str:
    """Build LRC lyrics content from a chapter's SMIL timings and text.

    Args:
        chapter: A parsed ChapterOverlay with timings and id_to_text.
        time_offset: Optional time offset in seconds to add to timestamps.

    Returns:
        LRC formatted string.
    """
    lines: list[str] = []
    for element_id, clip_begin, _clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        total_seconds = max(clip_begin + time_offset, 0.0)
        minutes = int(total_seconds // 60)
        seconds = total_seconds - (minutes * 60)
        lines.append(f"[{minutes:02d}:{seconds:05.2f}] {text}")
    return "\n".join(lines)


def build_srt_from_chapter(
    chapter: ChapterOverlay, time_offset: float = 0.0, start_index: int = 1, center: bool = False
) -> tuple[str, int]:
    """Build SRT subtitle content from a chapter's SMIL timings and text."""
    blocks: list[str] = []
    idx = start_index
    for element_id, clip_begin, clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        start_str = format_timestamp(clip_begin + time_offset, ",")
        end_str = format_timestamp(clip_end + time_offset, ",")
        if center:
            text = "{\\an5}" + text
        blocks.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")
        idx += 1
    return "\n".join(blocks), idx


def build_vtt_from_chapter(
    chapter: ChapterOverlay, time_offset: float = 0.0, start_index: int = 1, center: bool = False
) -> tuple[str, int]:
    """Build WebVTT subtitle blocks from a chapter's SMIL timings and text."""
    blocks: list[str] = []
    idx = start_index
    for element_id, clip_begin, clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        start_str = format_timestamp(clip_begin + time_offset, ".")
        end_str = format_timestamp(clip_end + time_offset, ".")
        cue_settings = " align:center line:50%" if center else ""
        blocks.append(f"{idx}\n{start_str} --> {end_str}{cue_settings}\n{text}\n")
        idx += 1
    return "\n".join(blocks), idx


def build_ass_from_chapter(
    chapter: ChapterOverlay, time_offset: float = 0.0, book_title: str = "Chapter", center: bool = False
) -> str:
    """Build ASS subtitle content from a chapter's SMIL timings and text."""
    alignment = "5" if center else "2"
    lines = [
        "[Script Info]",
        f"Title: {book_title}",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "PlayResX: 640",
        "PlayResY: 360",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,1,{alignment},10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for element_id, clip_begin, clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        text = text.replace("\n", r"\N")
        start_str = format_ass_timestamp(clip_begin + time_offset)
        end_str = format_ass_timestamp(clip_end + time_offset)
        lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")
    return "\n".join(lines)


def build_ass_merged(chapters: list[ChapterOverlay], book_title: str, center: bool = False) -> str:
    """Build a single merged ASS file from multiple chapters."""
    alignment = "5" if center else "2"
    lines = [
        "[Script Info]",
        f"Title: {book_title}",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "PlayResX: 640",
        "PlayResY: 360",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,1,{alignment},10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    time_offset = 0.0
    for chapter in chapters:
        for element_id, clip_begin, clip_end in chapter.timings:
            text = chapter.id_to_text.get(element_id, "")
            if not text:
                continue
            text = text.replace("\n", r"\N")
            start_str = format_ass_timestamp(clip_begin + time_offset)
            end_str = format_ass_timestamp(clip_end + time_offset)
            lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")
        if chapter.timings:
            _elem_id, _begin, last_end = chapter.timings[-1]
            time_offset += last_end
    return "\n".join(lines)


def build_ttml_from_chapter(chapter: ChapterOverlay, time_offset: float = 0.0, center: bool = False) -> str:
    """Build TTML subtitle content from a chapter's SMIL timings and text."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:tts="http://www.w3.org/ns/ttml#styling" xml:lang="en">',
        '  <head>',
        '    <styling>',
        '      <style xml:id="s1" tts:textAlign="center" tts:fontFamily="Arial" tts:fontSize="100%"/>',
        '    </styling>',
    ]
    if center:
        lines.extend([
            '    <layout>',
            '      <region xml:id="r_center" tts:displayAlign="center" tts:textAlign="center"/>',
            '    </layout>'
        ])
    lines.extend([
        '  </head>',
        '  <body>',
        '    <div>',
    ])
    for element_id, clip_begin, clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        start_str = format_timestamp(clip_begin + time_offset, ".")
        end_str = format_timestamp(clip_end + time_offset, ".")
        escaped_text = escape_xml(text)
        region_attr = ' region="r_center"' if center else ''
        lines.append(
            f'      <p begin="{start_str}" end="{end_str}" style="s1"{region_attr}>{escaped_text}</p>'
        )
    lines.extend(["    </div>", "  </body>", "</tt>"])
    return "\n".join(lines)


def build_ttml_merged(chapters: list[ChapterOverlay], center: bool = False) -> str:
    """Build a single merged TTML file from multiple chapters."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:tts="http://www.w3.org/ns/ttml#styling" xml:lang="en">',
        '  <head>',
        '    <styling>',
        '      <style xml:id="s1" tts:textAlign="center" tts:fontFamily="Arial" tts:fontSize="100%"/>',
        '    </styling>',
    ]
    if center:
        lines.extend([
            '    <layout>',
            '      <region xml:id="r_center" tts:displayAlign="center" tts:textAlign="center"/>',
            '    </layout>'
        ])
    lines.extend([
        '  </head>',
        '  <body>',
        '    <div>',
    ])
    time_offset = 0.0
    for chapter in chapters:
        for element_id, clip_begin, clip_end in chapter.timings:
            text = chapter.id_to_text.get(element_id, "")
            if not text:
                continue
            start_str = format_timestamp(clip_begin + time_offset, ".")
            end_str = format_timestamp(clip_end + time_offset, ".")
            escaped_text = escape_xml(text)
            region_attr = ' region="r_center"' if center else ''
            lines.append(
                f'      <p begin="{start_str}" end="{end_str}" style="s1"{region_attr}>{escaped_text}</p>'
            )
        if chapter.timings:
            _elem_id, _begin, last_end = chapter.timings[-1]
            time_offset += last_end
    lines.extend(["    </div>", "  </body>", "</tt>"])
    return "\n".join(lines)


def build_sbv_from_chapter(chapter: ChapterOverlay, time_offset: float = 0.0) -> str:
    """Build YouTube SBV subtitle content from a chapter's SMIL timings and text."""
    blocks: list[str] = []
    for element_id, clip_begin, clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if not text:
            continue
        start_str = format_sbv_timestamp(clip_begin + time_offset)
        end_str = format_sbv_timestamp(clip_end + time_offset)
        blocks.append(f"{start_str},{end_str}\n{text}\n")
    return "\n".join(blocks)


def build_sbv_merged(chapters: list[ChapterOverlay]) -> str:
    """Build a single merged SBV file from multiple chapters."""
    blocks: list[str] = []
    time_offset = 0.0
    for chapter in chapters:
        content = build_sbv_from_chapter(chapter, time_offset=time_offset)
        if content:
            blocks.append(content)
        if chapter.timings:
            _elem_id, _begin, last_end = chapter.timings[-1]
            time_offset += last_end
    return "\n".join(blocks)


def build_txt_from_chapter(chapter: ChapterOverlay) -> str:
    """Build plain text transcript from a chapter."""
    lines: list[str] = []
    for element_id, _clip_begin, _clip_end in chapter.timings:
        text = chapter.id_to_text.get(element_id, "")
        if text:
            lines.append(text)
    return "\n".join(lines)


def build_txt_merged(chapters: list[ChapterOverlay]) -> str:
    """Build a single merged TXT transcript file from multiple chapters."""
    lines: list[str] = []
    for chapter in chapters:
        content = build_txt_from_chapter(chapter)
        if content:
            lines.append(content)
    return "\n".join(lines)


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name or "chapter"


def epub_to_audio_subtitles(
    epub_path: str | Path,
    output_dir: str | Path,
    merge: bool = False,
    formats: list[str] | None = None,
    center: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    mp4_video: bool = False,
    include_audio: bool = True,
    embed_subtitles: bool = False,
    cover_art: str | Path | None = None,
    audio_format: str = "m4b",
) -> list[tuple[Path | None, list[Path]]]:
    """Extract audio tracks and multiple subtitle formats from an EPUB3 with Media Overlays.

    Args:
        epub_path: Path to the input EPUB3 file.
        output_dir: Directory to write output files.
        merge: If True, merge all chapters into a single audio + subtitle set.
        formats: List of subtitle formats to export (e.g., ["ass", "srt", "vtt", "ttml", "sbv", "lrc", "txt"]).
                 Defaults to ["ass"].
        center: If True, center alignment vertically and horizontally.
        progress_callback: Optional callback for status messages.
        mp4_video: If True, convert the audio to MP4 video using a static black video.
        include_audio: If True, extract/compile audiobook files.
        embed_subtitles: If True and mp4_video is True, burn subtitles into the MP4 video.
        cover_art: Optional path to custom cover art image.
        audio_format: Audio container format — 'm4b' (with chapters) or 'm4a' (without chapters).

    Returns:
        List of (audio_path, list_of_subtitle_paths) tuples.
    """
    epub_path = Path(epub_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if mp4_video and not include_audio:
        raise ValueError("Cannot convert to MP4 video without including the audio.")

    if formats is None:
        formats = ["ass"]

    # Canonicalize formats
    formats = [f.lower().strip() for f in formats if f.strip()]

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

    # Extract book title, author, and ASIN/identifier from EPUB metadata
    book_title = epub_path.stem
    author = "Unknown"
    asin = ""
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
                    creator_el = opf_root.find(".//{*}creator")
                    if creator_el is not None and creator_el.text:
                        author = creator_el.text.strip()
                    for id_el in opf_root.findall(".//{*}identifier"):
                        if id_el.text:
                            asin = id_el.text.strip()
                            break
    except Exception:
        pass

    if not merge:
        chapter_outputs: list[tuple[Path | None, list[Path]]] = []
        with zipfile.ZipFile(epub_path, "r") as zf:
            for idx, chapter in enumerate(chapters):
                _log(f"Extracting chapter {idx + 1}/{len(chapters)}: {chapter.idref}")

                chapter_name = _sanitize_filename(f"{idx + 1:02d}_{chapter.idref}")
                
                sub_paths: list[Path] = []
                sub_for_embedding = None
                for fmt in formats:
                    sub_out = output_dir / f"{chapter_name}.{fmt}"
                    if fmt == "ass":
                        content = build_ass_from_chapter(chapter, book_title=book_title, center=center)
                    elif fmt == "srt":
                        content, _ = build_srt_from_chapter(chapter, center=center)
                    elif fmt == "vtt":
                        ch_content, _ = build_vtt_from_chapter(chapter, center=center)
                        content = "WEBVTT\n\n" + ch_content
                    elif fmt == "ttml":
                        content = build_ttml_from_chapter(chapter, center=center)
                    elif fmt == "sbv":
                        content = build_sbv_from_chapter(chapter)
                    elif fmt == "lrc":
                        content = build_lrc_from_chapter(chapter)
                    elif fmt == "txt":
                        content = build_txt_from_chapter(chapter)
                    else:
                        _log(f"  Warning: unsupported subtitle format: {fmt}")
                        continue
                    
                    sub_out.write_text(content, encoding="utf-8")
                    sub_paths.append(sub_out)
                    if fmt == "ass":
                        sub_for_embedding = sub_out
                    elif fmt == "srt" and not sub_for_embedding:
                        sub_for_embedding = sub_out

                audio_out = None
                if include_audio:
                    audio_ext = Path(chapter.audio_href).suffix or ".mp3"
                    temp_audio_out = output_dir / f"temp_{chapter_name}{audio_ext}"
                    try:
                        audio_data = zf.read(chapter.audio_href)
                        temp_audio_out.write_bytes(audio_data)
                    except KeyError:
                        _log(f"  Warning: audio file not found in EPUB: {chapter.audio_href}")
                        continue

                    audio_out_ext = ".m4a" if audio_format == "m4a" else ".m4b"
                    audio_out_path = output_dir / f"{chapter_name}{audio_out_ext}"
                    
                    # Resolve cover art
                    temp_cover = None
                    if cover_art and Path(cover_art).exists():
                        temp_cover = Path(cover_art)
                    else:
                        extracted_cover_path = output_dir / f"extracted_cover_{idx}.jpg"
                        if _extract_epub_cover(epub_path, extracted_cover_path):
                            temp_cover = extracted_cover_path
                    
                    processed_cover = None
                    if temp_cover:
                        processed_cover = output_dir / f"cover_{idx}_processed.jpg"
                        processed_cover = _process_cover_art(temp_cover, processed_cover)

                    chapter_metadata = {
                        "title": chapter.title,
                        "artist": author,
                        "album": book_title,
                        "genre": "Audiobook",
                        "comment": "Bookmarking enabled",
                    }
                    if asin:
                        chapter_metadata["asin"] = asin

                    duration = _get_audio_duration(temp_audio_out)
                    if duration == 0.0 and chapter.timings:
                        duration = chapter.timings[-1][2]

                    _log(f"  Compiling {chapter_name}{audio_out_ext}...")
                    if audio_format == "m4a":
                        _convert_to_m4a(
                            input_audio=temp_audio_out,
                            output_path=audio_out_path,
                            metadata=chapter_metadata,
                            cover_art=processed_cover
                        )
                    else:
                        _convert_to_m4b(
                            input_audio=temp_audio_out,
                            output_path=audio_out_path,
                            metadata=chapter_metadata,
                            chapters=[chapter],
                            chapter_durations=[duration],
                            cover_art=processed_cover
                        )

                    # Cleanup
                    temp_audio_out.unlink(missing_ok=True)
                    if processed_cover:
                        processed_cover.unlink(missing_ok=True)
                    if temp_cover and temp_cover.name.startswith("extracted_cover_"):
                        temp_cover.unlink(missing_ok=True)

                    audio_out = audio_out_path

                    if mp4_video:
                        mp4_out = audio_out.with_suffix(".mp4")
                        _log(f"  Converting {audio_out.name} to video...")
                        
                        burn_sub_path = None
                        temp_burn_sub = None
                        if embed_subtitles:
                            if sub_for_embedding:
                                burn_sub_path = sub_for_embedding
                            else:
                                ass_content = build_ass_from_chapter(chapter, book_title=book_title, center=center)
                                temp_burn_sub = tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8")
                                temp_burn_sub.write(ass_content)
                                temp_burn_sub.close()
                                burn_sub_path = Path(temp_burn_sub.name)

                        _audio_to_mp4_video(audio_out, mp4_out, subtitle_path=burn_sub_path)
                        
                        if temp_burn_sub:
                            Path(temp_burn_sub.name).unlink(missing_ok=True)
                        audio_out.unlink(missing_ok=True)
                        audio_out = mp4_out

                chapter_outputs.append((audio_out, sub_paths))
                sub_names = ", ".join(p.name for p in sub_paths)
                audio_name = audio_out.name if audio_out else "No audio"
                _log(f"  ✓ {audio_name} + [{sub_names}]")

        if not chapter_outputs:
            raise ValueError("No files could be extracted from the EPUB.")

        _log(f"Done! Extracted {len(chapter_outputs)} chapter(s) to {output_dir}")
        return chapter_outputs

    # Merged mode
    _log("Merging all chapters...")
    audio_ext = Path(chapters[0].audio_href).suffix or ".mp3"
    merged_name = _sanitize_filename(book_title)
    merged_audio_ext = ".m4a" if audio_format == "m4a" else ".m4b"
    merged_audio_out = output_dir / f"{merged_name}{merged_audio_ext}"

    temp_audio_paths: list[Path] = []
    chapter_durations: list[float] = []
    with zipfile.ZipFile(epub_path, "r") as zf:
        for idx, chapter in enumerate(chapters):
            chapter_name = _sanitize_filename(f"temp_{idx + 1:02d}_{chapter.idref}")
            audio_out = output_dir / f"{chapter_name}{audio_ext}"
            try:
                audio_data = zf.read(chapter.audio_href)
                audio_out.write_bytes(audio_data)
                temp_audio_paths.append(audio_out)
                
                dur = _get_audio_duration(audio_out)
                if dur == 0.0 and chapter.timings:
                    dur = chapter.timings[-1][2]
                chapter_durations.append(dur)
            except KeyError:
                _log(f"  Warning: audio file not found in EPUB: {chapter.audio_href}")
                continue

    if not temp_audio_paths:
        raise ValueError("No audio files could be extracted for merging.")

    if include_audio:
        temp_merged_audio = output_dir / f"temp_merged_{merged_name}{audio_ext}"
        _merge_audio_files(temp_audio_paths, temp_merged_audio)
        
        _log(f"Converting merged audio to {merged_audio_ext.upper().lstrip('.')} audiobook...")
        temp_cover = None
        if cover_art and Path(cover_art).exists():
            temp_cover = Path(cover_art)
        else:
            extracted_cover_path = output_dir / "extracted_cover_merged.jpg"
            if _extract_epub_cover(epub_path, extracted_cover_path):
                temp_cover = extracted_cover_path
        
        processed_cover = None
        if temp_cover:
            processed_cover = output_dir / "cover_merged_processed.jpg"
            processed_cover = _process_cover_art(temp_cover, processed_cover)

        merged_metadata = {
            "title": book_title,
            "artist": author,
            "album": book_title,
            "genre": "Audiobook",
            "comment": "Bookmarking enabled",
        }
        if asin:
            merged_metadata["asin"] = asin

        if audio_format == "m4a":
            _convert_to_m4a(
                input_audio=temp_merged_audio,
                output_path=merged_audio_out,
                metadata=merged_metadata,
                cover_art=processed_cover
            )
        else:
            _convert_to_m4b(
                input_audio=temp_merged_audio,
                output_path=merged_audio_out,
                metadata=merged_metadata,
                chapters=chapters,
                chapter_durations=chapter_durations,
                cover_art=processed_cover
            )
        
        temp_merged_audio.unlink(missing_ok=True)
        if processed_cover:
            processed_cover.unlink(missing_ok=True)
        if temp_cover and temp_cover.name.startswith("extracted_cover_"):
            temp_cover.unlink(missing_ok=True)
        
        final_audio = merged_audio_out
    else:
        final_audio = None

    for path in temp_audio_paths:
        path.unlink(missing_ok=True)

    merged_subs: list[Path] = []
    sub_for_embedding = None
    for fmt in formats:
        sub_out = output_dir / f"{merged_name}.{fmt}"
        
        if fmt == "ass":
            content = build_ass_merged(chapters, book_title=book_title, center=center)
        elif fmt == "srt":
            blocks: list[str] = []
            time_offset = 0.0
            start_index = 1
            for chapter in chapters:
                ch_content, next_idx = build_srt_from_chapter(chapter, time_offset=time_offset, start_index=start_index, center=center)
                if ch_content:
                    blocks.append(ch_content)
                    start_index = next_idx
                if chapter.timings:
                    _elem_id, _begin, last_end = chapter.timings[-1]
                    time_offset += last_end
            content = "\n".join(blocks)
        elif fmt == "vtt":
            blocks: list[str] = []
            time_offset = 0.0
            start_index = 1
            for chapter in chapters:
                ch_content, next_idx = build_vtt_from_chapter(chapter, time_offset=time_offset, start_index=start_index, center=center)
                if ch_content:
                    blocks.append(ch_content)
                    start_index = next_idx
                if chapter.timings:
                    _elem_id, _begin, last_end = chapter.timings[-1]
                    time_offset += last_end
            content = "WEBVTT\n\n" + "\n".join(blocks)
        elif fmt == "ttml":
            content = build_ttml_merged(chapters, center=center)
        elif fmt == "sbv":
            content = build_sbv_merged(chapters)
        elif fmt == "lrc":
            blocks = []
            time_offset = 0.0
            for chapter in chapters:
                ch_content = build_lrc_from_chapter(chapter, time_offset=time_offset)
                if ch_content:
                    blocks.append(ch_content)
                if chapter.timings:
                    _elem_id, _begin, last_end = chapter.timings[-1]
                    time_offset += last_end
            content = "\n".join(blocks)
        elif fmt == "txt":
            content = build_txt_merged(chapters)
        else:
            _log(f"  Warning: unsupported subtitle format: {fmt}")
            continue

        sub_out.write_text(content, encoding="utf-8")
        merged_subs.append(sub_out)
        if fmt == "ass":
            sub_for_embedding = sub_out
        elif fmt == "srt" and not sub_for_embedding:
            sub_for_embedding = sub_out

    if mp4_video and final_audio:
        mp4_out = final_audio.with_suffix(".mp4")
        _log(f"Converting merged audio {final_audio.name} to video...")
        
        burn_sub_path = None
        temp_burn_sub = None
        if embed_subtitles:
            if sub_for_embedding:
                burn_sub_path = sub_for_embedding
            else:
                ass_content = build_ass_merged(chapters, book_title=book_title, center=center)
                temp_burn_sub = tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8")
                temp_burn_sub.write(ass_content)
                temp_burn_sub.close()
                burn_sub_path = Path(temp_burn_sub.name)

        _audio_to_mp4_video(final_audio, mp4_out, subtitle_path=burn_sub_path)
        
        if temp_burn_sub:
            Path(temp_burn_sub.name).unlink(missing_ok=True)
        final_audio.unlink(missing_ok=True)
        final_audio = mp4_out

    sub_names = ", ".join(p.name for p in merged_subs)
    audio_name = final_audio.name if final_audio else "No audio"
    _log(f"Done! Merged output: {audio_name} + [{sub_names}]")
    return [(final_audio, merged_subs)]


def epub_to_mp3_lrc(
    epub_path: str | Path,
    output_dir: str | Path,
    merge: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> list[tuple[Path | None, Path]]:
    """Backward compatibility wrapper mapping to epub_to_audio_subtitles."""
    results = epub_to_audio_subtitles(
        epub_path=epub_path,
        output_dir=output_dir,
        merge=merge,
        formats=["lrc"],
        progress_callback=progress_callback,
    )
    return [(audio, subs[0]) for audio, subs in results]


def _merge_audio_files(audio_paths: list[Path], output_path: Path) -> None:
    """Concatenate multiple audio files using ffmpeg's concat demuxer."""
    if not audio_paths:
        return
    if len(audio_paths) == 1:
        shutil.copy2(audio_paths[0], output_path)
        return

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as list_file:
        for audio in audio_paths:
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


def _audio_to_mp4_video(audio_path: Path, output_path: Path, subtitle_path: Path | None = None) -> None:
    """Convert an audio file to an MP4 video with a static black screen using ffmpeg."""
    # Query audio duration using ffprobe to avoid -shortest stopping on cover art streams
    duration = None
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        dur_str = res.stdout.decode().strip()
        if dur_str:
            duration = float(dur_str)
    except Exception:
        pass

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "color=c=black:s=640x360:r=10",
            "-i", str(audio_path),
        ]
        if subtitle_path:
            escaped_sub_path = str(subtitle_path.resolve()).replace(":", "\\:").replace("\\", "/")
            cmd.extend(["-filter:v:0", f"subtitles='{escaped_sub_path}'"])
        cmd.extend([
            "-map", "0:v",
            "-map", "1:a",
            "-map", "1:v?",
            "-c:v:0", "libx264",
            "-preset", "veryfast",
            "-crf", "32",
            "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-c:v:1", "copy",
            "-disposition:v:1", "attached_pic",
        ])
        if duration is not None:
            cmd.extend(["-t", f"{duration:.3f}"])
        else:
            cmd.extend(["-shortest"])
        cmd.append(str(output_path))

        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg MP4 conversion failed: {stderr}") from e
