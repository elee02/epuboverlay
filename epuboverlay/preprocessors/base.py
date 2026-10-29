from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re
from typing import List
import uuid
import zipfile

# --- Document Models ---

@dataclass
class DocumentSection:
    """Represents a logically split section of a document."""
    id: str           # Unique identifier (e.g. "chapter_1#sec_2")
    title: str        # Display title
    text_content: str # Extracted plain text for synthesis
    char_count: int   # Length of text_content
    preview: str      # Text snippet for preview lists


# --- Base Interface ---

class BasePreprocessor:
    """Abstract base class for all file type preprocessors."""
    
    def can_handle(self, file_path: Path) -> bool:
        """Return True if this preprocessor can handle the given file."""
        raise NotImplementedError
        
    def extract_sections(self, file_path: Path) -> List[DocumentSection]:
        """Extract sections from the given file."""
        raise NotImplementedError


# --- Common helpers ---

def ends_with_terminal_punctuation(text: str) -> bool:
    """Return True if the text ends with sentence-terminating punctuation."""
    text_stripped = text.strip()
    if not text_stripped:
        return True
    return text_stripped[-1] in ('.', '?', '!', ':', ';', '"', "'", '”', '’')


def resolve_safe_path(root_dir: Path, target_path: Path) -> Path:
    """Ensure target_path resolves inside root_dir to prevent path traversal."""
    root_resolved = root_dir.resolve()
    target_resolved = target_path.resolve()
    if not target_resolved.is_relative_to(root_resolved):
        raise ValueError(f"Unsafe path traversal outside workspace blocked: {target_path}")
    return target_resolved


def safe_extract_zip(
    zf: zipfile.ZipFile,
    dest_dir: Path,
    max_total_size: int = 1024 * 1024 * 1024,
) -> None:
    """Safely extract a ZipFile while preventing Zip Slip traversal and zip bombs."""
    dest_resolved = dest_dir.resolve()
    total_size = 0
    for member in zf.infolist():
        total_size += member.file_size
        if total_size > max_total_size:
            raise ValueError(
                f"Archive uncompressed size exceeds maximum limit ({max_total_size} bytes)."
            )
        target = (dest_resolved / member.filename).resolve()
        if not target.is_relative_to(dest_resolved):
            raise ValueError(
                f"Unsafe archive entry path traversal blocked: {member.filename}"
            )
    zf.extractall(dest_resolved)


def build_epub_from_sections(
    sections: List[DocumentSection],
    output_epub_path: Path,
    title: str = "Document",
) -> Path:
    """Package extracted DocumentSection objects into a minimal valid EPUB 3 archive."""
    output_epub_path = Path(output_epub_path)
    output_epub_path.parent.mkdir(parents=True, exist_ok=True)

    if not sections:
        sections = [
            DocumentSection(
                id="section_0",
                title=title or "Document",
                text_content="Empty document.",
                char_count=15,
                preview="Empty document.",
            )
        ]

    book_uid = f"urn:uuid:{uuid.uuid4()}"
    escaped_book_title = html.escape(title or "Document")

    manifest_entries: list[str] = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    ]
    spine_entries: list[str] = []
    nav_entries: list[str] = []
    chapter_files: list[tuple[str, str]] = []

    used_ids: set[str] = {"nav"}
    for idx, sec in enumerate(sections):
        raw_id = re.sub(r"[^A-Za-z0-9._-]", "_", sec.id or f"section_{idx}").strip("_")
        if not raw_id or not raw_id[0].isalpha():
            raw_id = f"sec_{raw_id or idx}"
        sec_id = raw_id
        suffix = 1
        while sec_id in used_ids:
            sec_id = f"{raw_id}_{suffix}"
            suffix += 1
        used_ids.add(sec_id)

        href = f"{sec_id}.xhtml"
        sec_title = html.escape(sec.title or f"Section {idx + 1}")
        manifest_entries.append(
            f'    <item id="{sec_id}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine_entries.append(f'    <itemref idref="{sec_id}"/>')
        nav_entries.append(f'        <li><a href="{href}">{sec_title}</a></li>')

        raw_paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n|\r\n\s*\r\n", sec.text_content or "")
            if p.strip()
        ]
        if not raw_paragraphs and (sec.text_content or "").strip():
            raw_paragraphs = [
                line.strip() for line in sec.text_content.splitlines() if line.strip()
            ]

        para_html = "\n".join(
            f"    <p>{html.escape(' '.join(p.split()))}</p>" for p in raw_paragraphs
        )
        xhtml_doc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
  <head>
    <meta charset="utf-8"/>
    <title>{sec_title}</title>
  </head>
  <body>
    <h1>{sec_title}</h1>
{para_html}
  </body>
</html>
"""
        chapter_files.append((f"OEBPS/{href}", xhtml_doc))

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">{book_uid}</dc:identifier>
    <dc:title>{escaped_book_title}</dc:title>
    <dc:language>en</dc:language>
    <meta property="epuboverlay:preprocessed">true</meta>
  </metadata>
  <manifest>
{chr(10).join(manifest_entries)}
  </manifest>
  <spine>
{chr(10).join(spine_entries)}
  </spine>
</package>
"""

    nav_xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
  <head>
    <meta charset="utf-8"/>
    <title>{escaped_book_title}</title>
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>Table of Contents</h1>
      <ol>
{chr(10).join(nav_entries)}
      </ol>
    </nav>
  </body>
</html>
"""

    with zipfile.ZipFile(output_epub_path, "w") as zf:
        zf.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "META-INF/container.xml",
            container_xml.encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.writestr(
            "OEBPS/content.opf",
            content_opf.encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.writestr(
            "OEBPS/nav.xhtml",
            nav_xhtml.encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for arcname, xhtml_str in chapter_files:
            zf.writestr(
                arcname,
                xhtml_str.encode("utf-8"),
                compress_type=zipfile.ZIP_DEFLATED,
            )

    return output_epub_path
