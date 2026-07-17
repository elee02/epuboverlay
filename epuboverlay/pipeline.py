from __future__ import annotations

from dataclasses import dataclass
import gc
import hashlib
from epuboverlay.normalization import normalize_text
from html.parser import HTMLParser
import html.entities
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Iterable, Protocol
import wave
import xml.etree.ElementTree as ET
import zipfile


@dataclass(frozen=True)
class TextChunk:
    text: str
    title: str | None = None
    idref: str | None = None


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
                chunks.append(TextChunk(text=text, idref=idref))

    return chunks


class _HTMLChapterInfoExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._current_tag: str | None = None
        self._title: str | None = None
        self._heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()

    def handle_endtag(self, tag: str) -> None:
        if self._current_tag == tag.lower():
            self._current_tag = None

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)
            if self._current_tag == "title" and not self._title:
                self._title = stripped
            elif self._current_tag in ("h1", "h2") and not self._heading:
                self._heading = stripped

    def text(self) -> str:
        return " ".join(self._parts).strip()

    def get_title(self) -> str:
        if self._heading:
            return self._heading
        if self._title:
            return self._title
        return ""


def parse_epub_toc(zf: zipfile.ZipFile, opf_path: str, opf_root: ET.Element) -> dict[str, str]:
    """Parse EPUB 3 Navigation Document (nav) or EPUB 2 NCX to map XHTML zip paths to titles."""
    toc_map: dict[str, str] = {}
    opf_dir = Path(opf_path).parent

    def _normalize(base: Path, href: str) -> str:
        combined = (base / href).as_posix()
        normalized = os.path.normpath(combined).replace("\\", "/")
        return normalized.lstrip("./").lstrip("/")

    # 1. Try EPUB 3 Navigation Document (nav)
    nav_href = None
    manifest_items = opf_root.findall(".//{*}manifest/{*}item")
    for item in manifest_items:
        properties = item.attrib.get("properties", "")
        if "nav" in properties.split():
            nav_href = item.attrib.get("href")
            break

    if nav_href:
        try:
            nav_zip_path = _normalize(opf_dir, nav_href)
            nav_content = zf.read(nav_zip_path)
            nav_root = ET.fromstring(nav_content)

            # Find all <a> tags inside <nav epub:type="toc"> or any <nav>
            for a_el in nav_root.findall(".//{*}a"):
                href = a_el.attrib.get("href", "").strip()
                if href:
                    clean_href = href.split("#")[0]
                    nav_dir = Path(nav_zip_path).parent
                    resolved_href = _normalize(nav_dir, clean_href)
                    
                    text = "".join(a_el.itertext()).strip()
                    if text and resolved_href not in toc_map:
                        toc_map[resolved_href] = text
        except Exception:
            pass

    # 2. Try EPUB 2 NCX file if EPUB 3 nav didn't yield anything
    if not toc_map:
        ncx_href = None
        for item in manifest_items:
            media_type = item.attrib.get("media-type", "")
            if media_type == "application/x-dtbncx+xml":
                ncx_href = item.attrib.get("href")
                break
        
        if ncx_href:
            try:
                ncx_zip_path = _normalize(opf_dir, ncx_href)
                ncx_content = zf.read(ncx_zip_path)
                ncx_root = ET.fromstring(ncx_content)
                
                for nav_point in ncx_root.findall(".//{*}navPoint"):
                    content_el = nav_point.find("{*}content")
                    label_el = nav_point.find(".//{*}navLabel/{*}text")
                    if content_el is not None and label_el is not None:
                        src = content_el.attrib.get("src", "").strip()
                        text = (label_el.text or "").strip()
                        if src and text:
                            clean_src = src.split("#")[0]
                            ncx_dir = Path(ncx_zip_path).parent
                            resolved_src = _normalize(ncx_dir, clean_src)
                            if resolved_src not in toc_map:
                                toc_map[resolved_src] = text
            except Exception:
                pass

    return toc_map


def extract_chapter_previews(epub_path: str | Path) -> list[dict]:
    """Extract ordered chapter metadata and previews for UI filtering."""
    epub_path = Path(epub_path)
    results = []
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
        toc_map = parse_epub_toc(zf, opf_path, opf_root)

        manifest: dict[str, str] = {}
        for item in opf_root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib.get("id")
            href = item.attrib.get("href")
            if item_id and href:
                manifest[item_id] = href

        base_dir = Path(opf_path).parent
        for itemref in opf_root.findall(".//{*}spine/{*}itemref"):
            idref = itemref.attrib.get("idref")
            href = manifest.get(idref or "")
            if not href:
                continue

            # Ensure we only process HTML/XHTML resources
            item = opf_root.find(f".//{{*}}manifest/{{*}}item[@id='{idref}']")
            if item is not None:
                media_type = item.attrib.get("media-type")
                if media_type != "application/xhtml+xml":
                    continue

            html_path = str((base_dir / href).as_posix())
            normalized_html_path = os.path.normpath(html_path).replace("\\", "/").lstrip("./").lstrip("/")
            if html_path not in zf.namelist():
                if normalized_html_path in zf.namelist():
                    html_path = normalized_html_path
                else:
                    continue

            extractor = _HTMLChapterInfoExtractor()
            extractor.feed(zf.read(html_path).decode("utf-8", errors="ignore"))
            text = extractor.text()
            
            title = toc_map.get(normalized_html_path)
            if not title:
                title = extractor.get_title() or idref or "Untitled Chapter"

            results.append({
                "idref": idref,
                "title": title,
                "char_count": len(text),
                "preview": text[:1000]
            })
    return results


def synthesize_with_internal_timestamps(
    chunks: Iterable[TextChunk],
    synthesizer: FrameTimedSynthesizer,
    frame_rate_hz: float,
    normalization_settings: dict | None = None,
) -> tuple[list[bytes], list[TimestampedLine]]:
    """Generate chunk audio and derive timestamps directly from generated frame counts."""
    if frame_rate_hz <= 0:
        raise ValueError("frame_rate_hz must be positive")

    current_frames = 0
    audio_chunks: list[bytes] = []
    timestamped_lines: list[TimestampedLine] = []

    for chunk in chunks:
        normalized_text = normalize_text(chunk.text, normalization_settings)
        audio, generated_frames = synthesizer.synthesize(normalized_text)
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


def replace_html_entities(xhtml_str: str) -> str:
    """Replace standard HTML named entities with XML-safe numeric character references."""
    def replace_entity(match: re.Match) -> str:
        name = match.group(1)
        if name in ("amp", "lt", "gt", "quot", "apos"):
            return match.group(0)
        num = html.entities.name2codepoint.get(name)
        if num is not None:
            return f"&#{num};"
        return match.group(0)

    return re.sub(r"&([a-zA-Z0-9]+);", replace_entity, xhtml_str)


def split_into_sentences(text: str) -> list[str]:
    """Split a paragraph into a list of sentences by protecting common abbreviations."""
    abbreviations = ["Mr.", "Mrs.", "Ms.", "Dr.", "St.", "Co.", "Ltd.", "Inc.", "e.g.", "i.e.", "vs."]
    
    protected_text = text
    for abbr in abbreviations:
        protected_text = re.sub(rf'\b{re.escape(abbr)}', abbr.replace(".", "_@_PERIOD_@_"), protected_text, flags=re.IGNORECASE)
        
    protected_text = re.sub(r'\b([A-Z])\.', r'\1_@_PERIOD_@_', protected_text)
    
    sentence_end = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'])')
    
    paragraphs = re.split(r'\n+', protected_text)
    sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        splits = sentence_end.split(para)
        for s in splits:
            s_clean = s.strip()
            if s_clean:
                s_restored = s_clean.replace("_@_PERIOD_@_", ".")
                sentences.append(s_restored)
    return sentences


def split_recursive(text: str, max_chars: int, level: int = 0) -> list[str]:
    """Recursively split a sentence/clause into smaller chunks using a hierarchy of pause boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Level 0: Clause punctuation (commas, semicolons, colons, em-dashes, en-dashes, parentheses, brackets)
    if level == 0:
        splits = re.split(r"(?<=[,;:\u2014\u2013\(\)\[\]])\s+", text)
    # Level 1: Coordinating conjunctions
    elif level == 1:
        splits = re.split(r"(\s+(?:and|but|or|yet|so)\s+)", text, flags=re.IGNORECASE)
    # Level 2: Subordinating conjunctions / transition words
    elif level == 2:
        splits = re.split(r"(\s+(?:because|although|though|since|while|which|that|who|when|where|if)\s+)", text, flags=re.IGNORECASE)
    # Level 3: Space (word boundaries fallback)
    else:
        words = text.split()
        splits = []
        current = []
        current_len = 0
        for w in words:
            if current_len + len(w) + (1 if current else 0) > max_chars:
                if current:
                    splits.append(" ".join(current))
                    current = [w]
                    current_len = len(w)
                else:
                    splits.append(w)
                    current = []
                    current_len = 0
            else:
                current.append(w)
                current_len += len(w) + (1 if current_len > 0 else 0)
        if current:
            splits.append(" ".join(current))
        return splits

    # Combine split separators (for levels 1 and 2) with the following text to keep phrasing natural
    if level in (1, 2):
        combined = []
        i = 0
        while i < len(splits):
            part = splits[i]
            if i + 1 < len(splits):
                sep = splits[i+1]
                if i + 2 < len(splits):
                    combined.append(part)
                    splits[i+2] = sep.strip() + " " + splits[i+2].strip()
                else:
                    combined.append(part + sep)
                i += 2
            else:
                combined.append(part)
                i += 1
        splits = [c.strip() for c in combined if c.strip()]
    else:
        splits = [s.strip() for s in splits if s.strip()]

    # If this level didn't split the text further, fall back to the next level
    if len(splits) <= 1:
        return split_recursive(text, max_chars, level + 1)

    chunks = []
    current_chunk = ""
    for part in splits:
        if not part:
            continue
        if len(part) > max_chars:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            chunks.extend(split_recursive(part, max_chars, level + 1))
        else:
            sep = " " if current_chunk else ""
            if len(current_chunk) + len(sep) + len(part) > max_chars:
                chunks.append(current_chunk)
                current_chunk = part
            else:
                current_chunk += sep + part
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def chunk_text(text: str, max_chars: int = 150) -> list[str]:
    """Break text down into smaller sentence-level or clause-level chunks."""
    sentences = split_into_sentences(text)
    chunks = []
    for sentence in sentences:
        chunks.extend(split_recursive(sentence, max_chars))
    return chunks



LEAF_BLOCKS = {
    "{http://www.w3.org/1999/xhtml}p", "p",
    "{http://www.w3.org/1999/xhtml}li", "li",
    "{http://www.w3.org/1999/xhtml}h1", "h1",
    "{http://www.w3.org/1999/xhtml}h2", "h2",
    "{http://www.w3.org/1999/xhtml}h3", "h3",
    "{http://www.w3.org/1999/xhtml}h4", "h4",
    "{http://www.w3.org/1999/xhtml}h5", "h5",
    "{http://www.w3.org/1999/xhtml}h6", "h6",
    "{http://www.w3.org/1999/xhtml}blockquote", "blockquote",
    "{http://www.w3.org/1999/xhtml}dd", "dd",
    "{http://www.w3.org/1999/xhtml}dt", "dt"
}

STRUCTURAL_BLOCKS = {
    "{http://www.w3.org/1999/xhtml}div", "div",
    "{http://www.w3.org/1999/xhtml}section", "section",
    "{http://www.w3.org/1999/xhtml}article", "article",
    "{http://www.w3.org/1999/xhtml}aside", "aside",
    "{http://www.w3.org/1999/xhtml}ol", "ol",
    "{http://www.w3.org/1999/xhtml}ul", "ul",
    "{http://www.w3.org/1999/xhtml}body", "body",
    "{http://www.w3.org/1999/xhtml}html", "html"
}


def clean_tag(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def contains_any_block(element: ET.Element) -> bool:
    for child in element.iter():
        if child is element:
            continue
        tag_name = clean_tag(child.tag)
        if tag_name in LEAF_BLOCKS or tag_name in STRUCTURAL_BLOCKS:
            return True
    return False


def segment_element_text(
    element: ET.Element,
    next_id_fn: callable,
    id_to_text_list: list[tuple[str, str]],
    max_chars: int = 150,
) -> None:
    text = element.text
    if not text or not text.strip():
        return

    sentences = chunk_text(text, max_chars)
    if not sentences:
        return

    element.text = None
    for i, sent in enumerate(sentences):
        span_id = next_id_fn()
        span = ET.Element("{http://www.w3.org/1999/xhtml}span", attrib={"id": span_id})
        span.text = sent
        if i < len(sentences) - 1:
            span.tail = " "
        element.append(span)
        id_to_text_list.append((span_id, sent))


def process_element(
    element: ET.Element,
    next_id_fn: callable,
    id_to_text_list: list[tuple[str, str]],
    max_chars: int = 150,
) -> None:
    tag_name = clean_tag(element.tag)

    if tag_name in LEAF_BLOCKS:
        if contains_any_block(element):
            for child in list(element):
                process_element(child, next_id_fn, id_to_text_list, max_chars)
        else:
            has_children = len(element) > 0
            if not has_children:
                segment_element_text(element, next_id_fn, id_to_text_list, max_chars)
            else:
                full_text = "".join(element.itertext()).strip()
                full_text = " ".join(full_text.split())
                if full_text:
                    sentences = chunk_text(full_text, max_chars)
                    if len(sentences) > 1 or len(full_text) > max_chars:
                        for child in list(element):
                            element.remove(child)
                        element.text = full_text
                        segment_element_text(element, next_id_fn, id_to_text_list, max_chars)
                    else:
                        span_id = element.attrib.get("id")
                        if not span_id:
                            span_id = next_id_fn()
                            element.attrib["id"] = span_id
                        id_to_text_list.append((span_id, full_text))
    else:
        for child in list(element):
            process_element(child, next_id_fn, id_to_text_list, max_chars)


def serialize_xhtml(root: ET.Element, original_content: bytes) -> bytes:
    """Serialize ElementTree root back into XHTML bytes, preserving doctypes."""
    doctype = b""
    first_lines = original_content.split(b"\n")[:5]
    for line in first_lines:
        line_strip = line.strip()
        if line_strip.startswith(b"<!DOCTYPE") or line_strip.startswith(b"<!doctype"):
            doctype = line_strip + b"\n"
            break

    ET.register_namespace("", "http://www.w3.org/1999/xhtml")
    ET.register_namespace("epub", "http://www.idpf.org/2007/ops")

    xml_data = ET.tostring(root, encoding="utf-8", method="xml")
    xml_decl = b'<?xml version="1.0" encoding="utf-8"?>\n'

    if xml_data.startswith(b"<?xml"):
        parts = xml_data.split(b"?>", 1)
        return parts[0] + b"?>\n" + doctype + parts[1]
    else:
        return xml_decl + doctype + xml_data


def serialize_opf(root: ET.Element) -> bytes:
    """Serialize OPF metadata file."""
    ET.register_namespace("", "http://www.idpf.org/2007/opf")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("opf", "http://www.idpf.org/2007/opf")
    return ET.tostring(root, encoding="utf-8", method="xml", xml_declaration=True)


def generate_smil_content(
    xhtml_filename: str,
    mappings: list[tuple[str, float, float]],
    audio_filename: str,
) -> str:
    """Generate standard EPUB 3 SMIL multimedia sync map."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">',
        "  <body>",
        f'    <seq epub:textref="{xhtml_filename}">'
    ]
    for element_id, begin, end in mappings:
        par_id = f"par_{element_id}"
        lines.append(f'      <par id="{par_id}">')
        lines.append(f'        <text src="{xhtml_filename}#{element_id}"/>')
        lines.append(
            f'        <audio src="{audio_filename}" clipBegin="{begin:.3f}s" clipEnd="{end:.3f}s"/>'
        )
        lines.append("      </par>")
    lines.append("    </seq>")
    lines.append("  </body>")
    lines.append("</smil>")
    return "\n".join(lines)


def concatenate_wavs(wav_chunks: list[bytes]) -> bytes:
    """Concatenate multiple 16-bit PCM WAV chunks in-memory using standard 'wave'."""
    if not wav_chunks:
        return b""
    if len(wav_chunks) == 1:
        return wav_chunks[0]

    first_io = io.BytesIO(wav_chunks[0])
    with wave.open(first_io, "rb") as wav_in:
        params = wav_in.getparams()

    out_io = io.BytesIO()
    with wave.open(out_io, "wb") as wav_out:
        wav_out.setparams(params)
        for chunk in wav_chunks:
            chunk_io = io.BytesIO(chunk)
            with wave.open(chunk_io, "rb") as wav_in:
                wav_out.writeframes(wav_in.readframes(wav_in.getnframes()))

    return out_io.getvalue()


def convert_wav_to_mp3(wav_bytes: bytes, output_path: Path) -> None:
    """Convert raw WAV bytes to compressed MP3 file using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "wav",
        "-i", "pipe:0",
        "-codec:a", "libmp3lame",
        "-qscale:a", "4",
        str(output_path)
    ]
    try:
        subprocess.run(
            cmd,
            input=wav_bytes,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg conversion failed: {stderr}") from e


def convert_wav_file_to_mp3(wav_path: Path, output_path: Path) -> None:
    """Convert a WAV file on disk to compressed MP3 using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame",
        "-qscale:a", "4",
        str(output_path)
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg conversion failed: {stderr}") from e


def convert_wav_file_to_m4a(wav_path: Path, output_path: Path) -> None:
    """Convert a WAV file on disk to M4A (AAC-LC) using ffmpeg.

    Uses CBR 64kbps AAC with the faststart flag for sample-accurate
    seeking via the MP4 container's seek table.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(wav_path),
        "-codec:a", "aac",
        "-b:a", "64k",
        "-movflags", "+faststart",
        str(output_path)
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg conversion failed: {stderr}") from e


def write_chunk_to_tempfile(audio_bytes: bytes, temp_dir: Path, idx: int, text_hash: str | None = None) -> tuple[Path, int]:
    """Write a single WAV chunk to a numbered temp file and return (path, frame_count).

    This avoids keeping all WAV buffers in memory simultaneously.
    """
    if text_hash:
        chunk_path = temp_dir / f"chunk_{idx:06d}_{text_hash}.wav"
    else:
        chunk_path = temp_dir / f"chunk_{idx:06d}.wav"
    chunk_path.write_bytes(audio_bytes)
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_in:
        frame_count = wav_in.getnframes()
    return chunk_path, frame_count


def stream_concat_wav_to_file(chunk_paths: list[Path], output_wav_path: Path) -> None:
    """Concatenate WAV chunk files into a single output WAV by streaming frames.

    Only one chunk is loaded into memory at a time, preventing OOM on large chapters.
    """
    if not chunk_paths:
        return

    # Read params from first chunk
    with wave.open(str(chunk_paths[0]), "rb") as first_wav:
        params = first_wav.getparams()

    with wave.open(str(output_wav_path), "wb") as wav_out:
        wav_out.setparams(params)
        for chunk_path in chunk_paths:
            with wave.open(str(chunk_path), "rb") as wav_in:
                wav_out.writeframes(wav_in.readframes(wav_in.getnframes()))


def format_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def compute_file_md5(file_path: Path) -> str:
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_duration_from_smil(smil_file_path: Path) -> float:
    try:
        tree = ET.parse(smil_file_path)
        root = tree.getroot()
        audio_elements = root.findall(".//{*}audio")
        if not audio_elements:
            return 0.0
        last_audio = audio_elements[-1]
        clip_end_str = last_audio.attrib.get("clipEnd", "0s")
        if clip_end_str.endswith("s"):
            clip_end_str = clip_end_str[:-1]
        return float(clip_end_str)
    except Exception as e:
        print(f"Error parsing SMIL file {smil_file_path}: {e}")
        return 0.0


# ── Private pipeline helpers ─────────────────────────────────────────────────


def _compute_config_hash(
    synthesizer: FrameTimedSynthesizer,
    frame_rate_hz: float,
    max_chars: int,
    normalization_settings: "dict | None",
) -> str:
    """Return a deterministic MD5 of the synthesis configuration.

    Used together with the EPUB content hash to partition the on-disk cache.
    """
    config_parts = [
        f"frame_rate_hz:{frame_rate_hz}",
        f"max_chars:{max_chars}",
        f"synth_type:{synthesizer.__class__.__name__}",
    ]
    if hasattr(synthesizer, "speed"):
        config_parts.append(f"speed:{synthesizer.speed}")
    if hasattr(synthesizer, "nfe_step"):
        config_parts.append(f"nfe_step:{synthesizer.nfe_step}")
    if hasattr(synthesizer, "ref_text"):
        config_parts.append(f"ref_text:{synthesizer.ref_text}")
    if hasattr(synthesizer, "ref_audio"):
        ref_audio_path = Path(synthesizer.ref_audio)
        if ref_audio_path.exists():
            stat = ref_audio_path.stat()
            config_parts.append(
                f"ref_audio:{ref_audio_path.resolve()}:{stat.st_size}:{stat.st_mtime}"
            )
        else:
            config_parts.append(f"ref_audio:{synthesizer.ref_audio}")
    if hasattr(synthesizer, "chars_per_sec"):
        config_parts.append(f"chars_per_sec:{synthesizer.chars_per_sec}")
    if hasattr(synthesizer, "sample_rate"):
        config_parts.append(f"sample_rate:{synthesizer.sample_rate}")
    if normalization_settings:
        config_parts.append(
            f"normalization_settings:{json.dumps(normalization_settings, sort_keys=True)}"
        )
    return hashlib.md5(",".join(config_parts).encode("utf-8")).hexdigest()


def _prepare_workspace(
    input_epub: Path,
    epub_hash: str,
    cache_dir_path: Path,
    emit_fn,
) -> Path:
    """Extract the EPUB into the cache workspace, reusing any existing extraction.

    Returns the workspace (tmp) directory path.
    """
    tmp_dir = cache_dir_path
    marker_file = tmp_dir / ".extracted"

    if not marker_file.exists() or marker_file.read_text().strip() != epub_hash:
        emit_fn("parsing", "Extracting EPUB contents to cache...")
        if tmp_dir.exists():
            for item in tmp_dir.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(input_epub, "r") as zf:
            zf.extractall(tmp_dir)
        marker_file.write_text(epub_hash)
    else:
        emit_fn("parsing", "Using existing extracted cache...")

    return tmp_dir


def _parse_opf(
    tmp_dir: Path,
) -> "tuple[Path, Path, ET.Element, ET.Element, ET.Element, dict, str]":
    """Parse META-INF/container.xml and the OPF package document.

    Returns:
        (opf_path, opf_dir, opf_root, manifest_node, spine_node,
         manifest_items, book_title)
    """
    container_path = tmp_dir / "META-INF/container.xml"
    if not container_path.exists():
        raise FileNotFoundError("META-INF/container.xml not found in EPUB")

    container_tree = ET.parse(container_path)
    rootfile = container_tree.find(".//{*}rootfile")
    if rootfile is None:
        raise ValueError("EPUB container is missing a rootfile entry")

    opf_rel_path = rootfile.attrib.get("full-path")
    if not opf_rel_path:
        raise ValueError("EPUB rootfile entry is missing full-path")

    opf_path = tmp_dir / opf_rel_path
    opf_dir = opf_path.parent
    opf_root = ET.parse(opf_path).getroot()

    book_title = tmp_dir.stem  # fallback; overwritten if OPF has a <title>
    title_el = opf_root.find(".//{*}title")
    if title_el is not None and title_el.text:
        book_title = title_el.text.strip()

    manifest_node = opf_root.find(".//{*}manifest")
    spine_node = opf_root.find(".//{*}spine")
    if manifest_node is None or spine_node is None:
        raise ValueError("OPF document is missing manifest or spine element")

    manifest_items: dict[str, ET.Element] = {}
    for item in manifest_node.findall(".//{*}item"):
        item_id = item.attrib.get("id")
        if item_id:
            manifest_items[item_id] = item

    return opf_path, opf_dir, opf_root, manifest_node, spine_node, manifest_items, book_title


def _precount_chapters(
    processable_itemrefs: list,
    opf_dir: Path,
    max_chars: int,
) -> "tuple[int, int]":
    """Pre-pass over every chapter to count pending synthesis chunks and characters.

    Returns:
        (total_chunks_to_synthesize, total_characters_all)
    """
    total_chunks = 0
    total_chars = 0

    for _itemref, pr_idref, _item, pr_href, pr_xhtml_file_path in processable_itemrefs:
        pr_rel_dir = Path(pr_href).parent
        pr_audio_filename = f"audio_{pr_idref}.m4a"
        pr_smil_filename = f"smil_{pr_idref}.smil"

        pr_audio_file_path = opf_dir / pr_rel_dir / "audio" / pr_audio_filename
        pr_smil_file_path = opf_dir / pr_rel_dir / pr_smil_filename
        pr_legacy_audio_path = opf_dir / "audio" / pr_audio_filename
        pr_legacy_smil_path = opf_dir / pr_smil_filename

        pr_is_cached = (
            (pr_audio_file_path.exists() or pr_legacy_audio_path.exists())
            and (pr_smil_file_path.exists() or pr_legacy_smil_path.exists())
        )

        try:
            pr_xhtml_str = pr_xhtml_file_path.read_bytes().decode("utf-8", errors="ignore")
            pr_xhtml_root = ET.fromstring(
                replace_html_entities(pr_xhtml_str).encode("utf-8")
            )
            pr_full_text = " ".join("".join(pr_xhtml_root.itertext()).strip().split())
            total_chars += len(pr_full_text)

            if not pr_is_cached:
                pr_id_to_text_list: list = []
                process_element(pr_xhtml_root, lambda: "dummy", pr_id_to_text_list, max_chars)
                total_chunks += len(pr_id_to_text_list)
        except Exception:
            pass

    return total_chunks, total_chars


def _synthesize_chapter_chunks(
    id_to_text_list: list,
    chapter_chunks_dir: Path,
    synthesizer: FrameTimedSynthesizer,
    normalization_settings: "dict | None",
    concurrency: int,
    executor,
    emit_fn,
    check_cancel_fn,
    state,
    chapter_idx: int,
    chapter_total: int,
    idref: str,
) -> list:
    """Synthesize all text chunks for one chapter, using the on-disk cache where possible.

    Handles both the concurrent (ThreadPoolExecutor) and sequential code paths.

    Returns:
        results: list of (chunk_path: Path, frame_count: int) in chunk order.
    """
    import time as _time

    chunk_total = len(id_to_text_list)
    results: list = [None] * chunk_total

    if concurrency > 1 and executor is not None:
        import threading as _threading
        from concurrent.futures import as_completed

        completed_chunks = 0
        progress_lock = _threading.Lock()

        def process_chunk(idx: int, _span_id: str, text: str):
            nonlocal completed_chunks
            check_cancel_fn()

            normalized_text = normalize_text(text, normalization_settings)
            text_hash = hashlib.md5(normalized_text.encode("utf-8")).hexdigest()[:16]
            chunk_path = chapter_chunks_dir / f"chunk_{idx:06d}_{text_hash}.wav"

            # Attempt to reuse existing chunk from cache
            cached_valid = False
            frame_count = 0
            if chunk_path.exists():
                try:
                    with wave.open(str(chunk_path), "rb") as wav_in:
                        frame_count = wav_in.getnframes()
                    cached_valid = True
                except Exception:
                    try:
                        chunk_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            if cached_valid:
                with progress_lock:
                    completed_chunks += 1
                    state.chunks_processed_so_far += 1
                    emit_fn(
                        "synthesizing",
                        f"Using cached chunk: {text[:30]}...",
                        chapter_idx=chapter_idx,
                        chapter_total=chapter_total,
                        chapter_name=idref,
                        chunk_idx=completed_chunks,
                        chunk_total=chunk_total,
                    )
                return idx, chunk_path, frame_count

            # Remove stale chunk files for this index slot
            for p in chapter_chunks_dir.glob(f"chunk_{idx:06d}*.wav"):
                if p != chunk_path:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass

            with progress_lock:
                if state.synthesis_start_time is None:
                    state.synthesis_start_time = _time.monotonic()
                emit_fn(
                    "synthesizing",
                    f"Synthesizing: {text[:60]}...",
                    chapter_idx=chapter_idx,
                    chapter_total=chapter_total,
                    chapter_name=idref,
                    chunk_idx=completed_chunks,
                    chunk_total=chunk_total,
                )

            audio, generated_frames = synthesizer.synthesize(normalized_text)
            if generated_frames < 0:
                raise ValueError("Synthesizer returned negative frame count")

            chunk_path, frame_count = write_chunk_to_tempfile(
                audio, chapter_chunks_dir, idx, text_hash
            )
            del audio  # release WAV bytes immediately

            with progress_lock:
                completed_chunks += 1
                state.chunks_processed_so_far += 1
                state.active_chunks_processed += 1
                emit_fn(
                    "synthesizing",
                    f"Finished chunk: {text[:30]}...",
                    chapter_idx=chapter_idx,
                    chapter_total=chapter_total,
                    chapter_name=idref,
                    chunk_idx=completed_chunks,
                    chunk_total=chunk_total,
                )
            return idx, chunk_path, frame_count

        futures = {
            executor.submit(process_chunk, idx, span_id, text): idx
            for idx, (span_id, text) in enumerate(id_to_text_list)
        }
        try:
            for future in as_completed(futures):
                check_cancel_fn()
                idx, chunk_path, frame_count = future.result()
                results[idx] = (chunk_path, frame_count)
        except Exception as exc:
            for f in futures:
                f.cancel()
            raise exc

    else:
        # Sequential synthesis
        for chunk_idx, (_span_id, text) in enumerate(id_to_text_list):
            check_cancel_fn()

            normalized_text = normalize_text(text, normalization_settings)
            text_hash = hashlib.md5(normalized_text.encode("utf-8")).hexdigest()[:16]
            chunk_path = chapter_chunks_dir / f"chunk_{chunk_idx:06d}_{text_hash}.wav"

            cached_valid = False
            frame_count = 0
            if chunk_path.exists():
                try:
                    with wave.open(str(chunk_path), "rb") as wav_in:
                        frame_count = wav_in.getnframes()
                    cached_valid = True
                except Exception:
                    try:
                        chunk_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            if cached_valid:
                results[chunk_idx] = (chunk_path, frame_count)
                state.chunks_processed_so_far += 1
                emit_fn(
                    "synthesizing",
                    f"Using cached chunk: {text[:30]}...",
                    chapter_idx=chapter_idx,
                    chapter_total=chapter_total,
                    chapter_name=idref,
                    chunk_idx=chunk_idx + 1,
                    chunk_total=chunk_total,
                )
            else:
                # Remove stale chunk files for this index slot
                for p in chapter_chunks_dir.glob(f"chunk_{chunk_idx:06d}*.wav"):
                    if p != chunk_path:
                        try:
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass

                if state.synthesis_start_time is None:
                    state.synthesis_start_time = _time.monotonic()
                emit_fn(
                    "synthesizing",
                    f"Synthesizing: {text[:60]}...",
                    chapter_idx=chapter_idx,
                    chapter_total=chapter_total,
                    chapter_name=idref,
                    chunk_idx=chunk_idx,
                    chunk_total=chunk_total,
                )
                audio, generated_frames = synthesizer.synthesize(normalized_text)
                if generated_frames < 0:
                    raise ValueError("Synthesizer returned negative frame count")
                chunk_path, frame_count = write_chunk_to_tempfile(
                    audio, chapter_chunks_dir, chunk_idx, text_hash
                )
                del audio  # release WAV bytes immediately
                results[chunk_idx] = (chunk_path, frame_count)
                state.chunks_processed_so_far += 1
                state.active_chunks_processed += 1
                emit_fn(
                    "synthesizing",
                    f"Finished chunk: {text[:30]}...",
                    chapter_idx=chapter_idx,
                    chapter_total=chapter_total,
                    chapter_name=idref,
                    chunk_idx=chunk_idx + 1,
                    chunk_total=chunk_total,
                )

    return results


def _register_chapter_in_opf(
    manifest_node: ET.Element,
    spine_item: ET.Element,
    idref: str,
    href: str,
    smil_filename: str,
    audio_filename: str,
) -> str:
    """Insert SMIL and audio <item> elements into the OPF manifest (if absent).

    Sets ``media-overlay`` on the spine item and returns the SMIL manifest ID.
    Safe to call for both freshly synthesised and already-cached chapters.
    """
    rel_dir = Path(href).parent
    smil_href = str((rel_dir / smil_filename).as_posix())
    audio_href = str((rel_dir / "audio" / audio_filename).as_posix())

    # Strip leading "./" that Path produces for same-directory hrefs
    if smil_href.startswith("./"):
        smil_href = smil_href[2:]
    if audio_href.startswith("./"):
        audio_href = audio_href[2:]

    smil_id = f"smil_{idref}"
    audio_id = f"audio_{idref}"

    existing_ids = {el.attrib.get("id") for el in manifest_node.findall(".//{*}item")}

    if smil_id not in existing_ids:
        manifest_node.append(
            ET.Element(
                "{http://www.idpf.org/2007/opf}item",
                attrib={
                    "id": smil_id,
                    "href": smil_href,
                    "media-type": "application/smil+xml",
                },
            )
        )

    if audio_id not in existing_ids:
        manifest_node.append(
            ET.Element(
                "{http://www.idpf.org/2007/opf}item",
                attrib={
                    "id": audio_id,
                    "href": audio_href,
                    "media-type": "audio/mp4",
                },
            )
        )

    spine_item.attrib["media-overlay"] = smil_id
    return smil_id


def _finalize_epub(
    opf_root: ET.Element,
    opf_path: Path,
    tmp_dir: Path,
    output_epub: Path,
    global_duration_secs: float,
    smil_durations: dict,
    emit_fn,
    chapter_total: int,
) -> None:
    """Write duration metadata to OPF, serialize it, then repackage the EPUB ZIP."""
    emit_fn(
        "packaging",
        "Adding duration metadata...",
        chapter_idx=chapter_total,
        chapter_total=chapter_total,
    )

    metadata_node = opf_root.find(".//{*}metadata")
    if metadata_node is not None:
        total_meta = ET.Element(
            "{http://www.idpf.org/2007/opf}meta",
            attrib={"property": "media:duration"},
        )
        total_meta.text = format_duration(global_duration_secs)
        metadata_node.append(total_meta)

        for smil_id, duration in smil_durations.items():
            chapter_meta = ET.Element(
                "{http://www.idpf.org/2007/opf}meta",
                attrib={"property": "media:duration", "refines": f"#{smil_id}"},
            )
            chapter_meta.text = format_duration(duration)
            metadata_node.append(chapter_meta)

    # Declare media overlay namespace prefix in OPF root
    prefix_val = opf_root.attrib.get("prefix", "")
    if "media:" not in prefix_val:
        opf_root.attrib["prefix"] = (
            (prefix_val.strip() + " media: http://www.idpf.org/2007/ops#").lstrip()
        )

    with open(opf_path, "wb") as f:
        f.write(serialize_opf(opf_root))

    emit_fn(
        "packaging",
        "Repackaging EPUB...",
        chapter_idx=chapter_total,
        chapter_total=chapter_total,
    )

    with zipfile.ZipFile(output_epub, "w") as zout:
        mimetype_path = tmp_dir / "mimetype"
        if mimetype_path.exists():
            zout.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        else:
            zout.writestr(
                "mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED
            )
        for file_path in tmp_dir.rglob("*"):
            if file_path.is_file() and file_path.name != "mimetype":
                rel_path = file_path.relative_to(tmp_dir)
                zout.write(
                    file_path,
                    str(rel_path.as_posix()),
                    compress_type=zipfile.ZIP_DEFLATED,
                )


# ── Public API ────────────────────────────────────────────────────────────────


def generate_media_overlay_epub(
    input_epub: str | Path,
    output_epub: str | Path,
    synthesizer: FrameTimedSynthesizer,
    frame_rate_hz: float,
    max_chars: int = 150,
    progress_callback: "Callable[[ProgressEvent], None] | None" = None,
    cancel_event: "threading.Event | None" = None,
    chapter_audio_callback: "Callable[[str, Path], None] | None" = None,
    cache_dir: str | Path | None = None,
    concurrency: int = 2,
    selected_chapters: list[str] | None = None,
    normalization_settings: dict | None = None,
) -> None:
    """Orchestrate EPUB extraction, synthesis, SMIL creation, OPF updates, and repackaging.

    Args:
        input_epub: Path to the input EPUB file.
        output_epub: Path to save the generated synced EPUB file.
        synthesizer: Synthesizer implementation to use.
        frame_rate_hz: Audio sample rate in Hz.
        max_chars: Maximum characters per chunk of synthesis.
        progress_callback: Optional callback receiving ProgressEvent updates.
        cancel_event: Optional threading.Event; if set, the pipeline will abort.
        chapter_audio_callback: Optional callback(idref, audio_path) called after each
            chapter's audio is written — enables per-chapter audio preview.
        cache_dir: Custom directory to cache intermediate files and skip already
            processed chapters.
        concurrency: Number of concurrent synthesis threads.
    """
    import threading
    import time as _time
    from types import SimpleNamespace
    from epuboverlay.progress import ProgressEvent

    input_epub = Path(input_epub)
    output_epub = Path(output_epub)
    start_time = _time.monotonic()

    # All mutable progress counters in one place so both _emit and helpers can
    # read/write them without a tangle of nonlocal declarations.
    state = SimpleNamespace(
        total_chunks_to_synthesize=0,
        chunks_processed_so_far=0,
        active_chunks_processed=0,
        total_characters_all=0,
        synthesis_start_time=None,
        global_duration_secs=0.0,
        book_title=input_epub.stem,
    )

    # Resolve cache directory from content + config hashes
    epub_hash = compute_file_md5(input_epub)
    config_hash = _compute_config_hash(
        synthesizer, frame_rate_hz, max_chars, normalization_settings
    )
    if cache_dir is None:
        cache_dir_path: Path = (
            Path.home() / ".epuboverlay" / "cache" / f"{epub_hash}_{config_hash}"
        )
    else:
        cache_dir_path = Path(cache_dir)

    # ── Progress emission closure ────────────────────────────────────────────
    def _emit(
        phase: str,
        message: str,
        chapter_idx: int = 0,
        chapter_total: int = 0,
        chapter_name: str = "",
        chunk_idx: int = 0,
        chunk_total: int = 0,
    ) -> None:
        elapsed = _time.monotonic() - start_time
        synthesis_elapsed = 0.0
        if state.synthesis_start_time is not None:
            synthesis_elapsed = _time.monotonic() - state.synthesis_start_time

        synth_speed = 1.0
        if hasattr(synthesizer, "speed") and synthesizer.speed > 0:
            synth_speed = synthesizer.speed

        estimated_hours = (
            state.total_characters_all / (15.0 * synth_speed * 3600.0)
            if state.total_characters_all > 0
            else 0.0
        )

        event = ProgressEvent(
            phase=phase,
            chapter_index=chapter_idx,
            chapter_total=chapter_total,
            chapter_name=chapter_name,
            chunk_index=chunk_idx,
            chunk_total=chunk_total,
            elapsed_seconds=elapsed,
            message=message,
            synthesis_elapsed_seconds=synthesis_elapsed,
            total_chunks_to_synthesize=state.total_chunks_to_synthesize,
            chunks_processed_so_far=state.chunks_processed_so_far,
            active_chunks_processed=state.active_chunks_processed,
            total_characters=state.total_characters_all,
            estimated_total_hours=estimated_hours,
            audiobook_duration_seconds=state.global_duration_secs,
        )
        if progress_callback is not None:
            progress_callback(event)

        if cache_dir_path is not None:
            try:
                data = {
                    "pid": os.getpid(),
                    "input_epub_path": str(input_epub.resolve()),
                    "output_epub_path": str(output_epub.resolve()),
                    "book_title": str(state.book_title),
                    "phase": phase,
                    "chapter_index": chapter_idx,
                    "chapter_total": chapter_total,
                    "chapter_name": chapter_name,
                    "chunk_index": chunk_idx,
                    "chunk_total": chunk_total,
                    "elapsed_seconds": elapsed,
                    "message": message,
                    "overall_percent": event.overall_percent,
                    "updated_at": _time.time(),
                    "total_chunks_to_synthesize": event.total_chunks_to_synthesize,
                    "chunks_processed_so_far": event.chunks_processed_so_far,
                    "active_chunks_processed": event.active_chunks_processed,
                    "total_characters": event.total_characters,
                    "estimated_total_hours": event.estimated_total_hours,
                    "audiobook_duration_seconds": event.audiobook_duration_seconds,
                }
                progress_file = cache_dir_path / "progress.json"
                temp_file = progress_file.with_suffix(".tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                temp_file.replace(progress_file)
            except Exception:
                pass

    def _check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            _emit("error", "Job cancelled by user.")
            raise RuntimeError("Job cancelled by user.")

    executor = None
    if concurrency > 1:
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=concurrency)

    try:
        # ── Phase 1: workspace ───────────────────────────────────────────────
        tmp_dir = _prepare_workspace(input_epub, epub_hash, cache_dir_path, _emit)

        # ── Phase 2: OPF parsing ─────────────────────────────────────────────
        opf_path, opf_dir, opf_root, manifest_node, spine_node, manifest_items, book_title = (
            _parse_opf(tmp_dir)
        )
        state.book_title = book_title

        # ── Build processable chapter list ───────────────────────────────────
        processable_itemrefs = []
        for itemref in spine_node.findall(".//{*}itemref"):
            idref = itemref.attrib.get("idref")
            item = manifest_items.get(idref or "")
            if item is None or item.attrib.get("media-type") != "application/xhtml+xml":
                continue
            href = item.attrib.get("href")
            xhtml_file_path = opf_dir / href
            if not xhtml_file_path.exists():
                continue
            if selected_chapters is not None and idref not in selected_chapters:
                continue
            processable_itemrefs.append((itemref, idref, item, href, xhtml_file_path))

        # ── Phase 3: pre-count chunks / characters ───────────────────────────
        state.total_chunks_to_synthesize, state.total_characters_all = _precount_chapters(
            processable_itemrefs, opf_dir, max_chars
        )
        chapter_total = len(processable_itemrefs)
        _emit("parsing", f"Found {chapter_total} chapters to process.",
              chapter_total=chapter_total)

        smil_durations: dict[str, float] = {}
        span_id_counter = 0

        def next_span_id() -> str:
            nonlocal span_id_counter
            span_id_counter += 1
            return f"epuboverlay-s-{span_id_counter}"

        # ── Phase 4: per-chapter synthesis loop ──────────────────────────────
        for chapter_idx, (itemref, idref, item, href, xhtml_file_path) in enumerate(
            processable_itemrefs
        ):
            _check_cancel()

            audio_filename = f"audio_{idref}.m4a"
            smil_filename = f"smil_{idref}.smil"
            rel_dir = Path(href).parent
            audio_dir = opf_dir / rel_dir / "audio"
            audio_file_path = audio_dir / audio_filename
            smil_file_path = opf_dir / rel_dir / smil_filename

            # Migrate legacy cache files (old layout had no rel_dir subfolder)
            legacy_audio_path = opf_dir / "audio" / audio_filename
            legacy_smil_path = opf_dir / smil_filename
            if legacy_audio_path.exists() and not audio_file_path.exists():
                audio_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy_audio_path), str(audio_file_path))
            if legacy_smil_path.exists() and not smil_file_path.exists():
                (opf_dir / rel_dir).mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy_smil_path), str(smil_file_path))

            # Check if this chapter is already fully cached
            chapter_duration = 0.0
            if (
                os.environ.get("EPUB_BYPASS_CACHE") != "1"
                and audio_file_path.exists()
                and smil_file_path.exists()
            ):
                chapter_duration = get_duration_from_smil(smil_file_path)

            if chapter_duration > 0.0 and audio_file_path.stat().st_size > 0:
                _emit("parsing", f"Using cached audio/SMIL for chapter: {idref}",
                      chapter_idx=chapter_idx, chapter_total=chapter_total,
                      chapter_name=idref)
                state.global_duration_secs += chapter_duration
                smil_id = _register_chapter_in_opf(
                    manifest_node, item, idref, href, smil_filename, audio_filename
                )
                smil_durations[smil_id] = chapter_duration
                if chapter_audio_callback is not None:
                    chapter_audio_callback(idref, audio_file_path)
                _emit("converting", f"Chapter {chapter_idx + 1}/{chapter_total} cached: {idref}",
                      chapter_idx=chapter_idx + 1, chapter_total=chapter_total,
                      chapter_name=idref)
                continue

            # ── Parse XHTML ──────────────────────────────────────────────────
            _emit("parsing", f"Parsing chapter: {idref}",
                  chapter_idx=chapter_idx, chapter_total=chapter_total,
                  chapter_name=idref)
            xhtml_bytes = xhtml_file_path.read_bytes()
            try:
                xhtml_root = ET.fromstring(
                    replace_html_entities(
                        xhtml_bytes.decode("utf-8", errors="ignore")
                    ).encode("utf-8")
                )
            except ET.ParseError as e:
                raise ValueError(f"Failed to parse XHTML file {href}: {e}") from e

            id_to_text_list: list = []
            process_element(xhtml_root, next_span_id, id_to_text_list, max_chars)
            if not id_to_text_list:
                continue

            chunk_total = len(id_to_text_list)

            # ── Phase 4a: synthesize chunks ──────────────────────────────────
            chapter_chunks_dir = tmp_dir / f"_chunks_{idref}"
            chapter_chunks_dir.mkdir(parents=True, exist_ok=True)

            results = _synthesize_chapter_chunks(
                id_to_text_list=id_to_text_list,
                chapter_chunks_dir=chapter_chunks_dir,
                synthesizer=synthesizer,
                normalization_settings=normalization_settings,
                concurrency=concurrency,
                executor=executor,
                emit_fn=_emit,
                check_cancel_fn=_check_cancel,
                state=state,
                chapter_idx=chapter_idx,
                chapter_total=chapter_total,
                idref=idref,
            )

            # ── Reconstruct per-chunk timings ────────────────────────────────
            chunk_paths = []
            current_time = 0.0
            mappings = []
            for chunk_idx, (span_id, _text) in enumerate(id_to_text_list):
                chunk_path, frame_count = results[chunk_idx]
                duration = frame_count / frame_rate_hz
                begin_time = current_time
                end_time = current_time + duration
                chunk_paths.append(chunk_path)
                mappings.append((span_id, begin_time, end_time))
                current_time = end_time

            if not chunk_paths:
                continue

            # ── Concatenate WAVs + encode M4A ────────────────────────────────
            _emit("converting", f"Concatenating audio for chapter: {idref}",
                  chapter_idx=chapter_idx, chapter_total=chapter_total,
                  chapter_name=idref, chunk_idx=chunk_total, chunk_total=chunk_total)
            chapter_wav_path = chapter_chunks_dir / "chapter_merged.wav"
            stream_concat_wav_to_file(chunk_paths, chapter_wav_path)

            audio_dir.mkdir(parents=True, exist_ok=True)
            _emit("converting", f"Converting to M4A: {idref}",
                  chapter_idx=chapter_idx, chapter_total=chapter_total,
                  chapter_name=idref, chunk_idx=chunk_total, chunk_total=chunk_total)
            convert_wav_file_to_m4a(chapter_wav_path, audio_file_path)
            shutil.rmtree(chapter_chunks_dir, ignore_errors=True)

            if chapter_audio_callback is not None:
                chapter_audio_callback(idref, audio_file_path)

            # ── Write XHTML + SMIL ───────────────────────────────────────────
            xhtml_file_path.write_bytes(serialize_xhtml(xhtml_root, xhtml_bytes))
            smil_file_path.write_text(
                generate_smil_content(
                    Path(href).name,
                    mappings,
                    f"audio/{audio_filename}",
                ),
                encoding="utf-8",
            )

            # ── Register in OPF manifest ─────────────────────────────────────
            smil_id = _register_chapter_in_opf(
                manifest_node, item, idref, href, smil_filename, audio_filename
            )
            chapter_duration = current_time
            state.global_duration_secs += chapter_duration
            smil_durations[smil_id] = chapter_duration

            _emit("converting", f"Chapter {chapter_idx + 1}/{chapter_total} complete: {idref}",
                  chapter_idx=chapter_idx + 1, chapter_total=chapter_total,
                  chapter_name=idref)

            # ── Explicit memory release ──────────────────────────────────────
            chunk_paths = None
            id_to_text_list = None
            xhtml_root = None
            results = None
            gc.collect()
            if "torch" in sys.modules:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)
            except Exception:
                pass

        # ── Phase 5: finalize ────────────────────────────────────────────────
        _finalize_epub(
            opf_root=opf_root,
            opf_path=opf_path,
            tmp_dir=tmp_dir,
            output_epub=output_epub,
            global_duration_secs=state.global_duration_secs,
            smil_durations=smil_durations,
            emit_fn=_emit,
            chapter_total=chapter_total,
        )

        elapsed = _time.monotonic() - start_time
        _emit("done", f"EPUB generated successfully in {elapsed:.1f}s → {output_epub}",
              chapter_idx=chapter_total, chapter_total=chapter_total)

    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        if cache_dir_path is not None:
            progress_file = cache_dir_path / "progress.json"
            if progress_file.exists():
                try:
                    progress_file.unlink()
                except Exception:
                    pass

