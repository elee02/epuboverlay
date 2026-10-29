from __future__ import annotations

from pathlib import Path
import shutil
import zipfile

from epuboverlay.preprocessors.base import (
    BasePreprocessor,
    DocumentSection,
    build_epub_from_sections,
    ends_with_terminal_punctuation,
    resolve_safe_path,
    safe_extract_zip,
)
from epuboverlay.preprocessors.epub import EPUBPreprocessor, preprocess_epub_workspace, merge_consecutive_paragraphs, split_xhtml_by_anchors
from epuboverlay.preprocessors.pdf import PDFPreprocessor
from epuboverlay.preprocessors.docx import DOCXPreprocessor
from epuboverlay.preprocessors.markdown import MarkdownPreprocessor
from epuboverlay.preprocessors.txt import TXTPreprocessor

__all__ = [
    "BasePreprocessor",
    "DocumentSection",
    "build_epub_from_sections",
    "ends_with_terminal_punctuation",
    "ensure_epub_file",
    "resolve_safe_path",
    "safe_extract_zip",
    "EPUBPreprocessor",
    "preprocess_epub_workspace",
    "merge_consecutive_paragraphs",
    "split_xhtml_by_anchors",
    "PDFPreprocessor",
    "DOCXPreprocessor",
    "MarkdownPreprocessor",
    "TXTPreprocessor",
    "get_preprocessor",
]


def get_preprocessor(file_path: Path) -> BasePreprocessor:
    """Factory to get the correct preprocessor for the given file."""
    preprocessors = [
        EPUBPreprocessor(),
        MarkdownPreprocessor(),
        TXTPreprocessor(),
        PDFPreprocessor(),
        DOCXPreprocessor(),
    ]
    for p in preprocessors:
        if p.can_handle(file_path):
            return p
    raise ValueError(f"No preprocessor found for file extension: {file_path.suffix}")


def _is_valid_epub_archive(file_path: Path) -> bool:
    """Return True if file_path is a ZIP archive containing META-INF/container.xml."""
    if not file_path.exists() or not zipfile.is_zipfile(file_path):
        return False
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return "META-INF/container.xml" in zf.namelist()
    except Exception:
        return False


def ensure_epub_file(
    input_path: Path,
    output_epub_path: Path | None = None,
    title: str | None = None,
) -> Path:
    """Ensure input_path is a valid EPUB 3 archive.

    If input_path has an .epub extension or is already a valid EPUB archive,
    copies it to output_epub_path (if given) or returns input_path directly.
    If input_path is a PDF, DOCX, Markdown, or TXT document, extracts its sections
    via get_preprocessor() and packages them into a valid EPUB 3 container at output_epub_path.
    """
    input_path = Path(input_path)
    if input_path.suffix.lower() == ".epub" or _is_valid_epub_archive(input_path):
        if output_epub_path is not None and input_path.resolve() != Path(output_epub_path).resolve():
            shutil.copy2(input_path, output_epub_path)
            return Path(output_epub_path)
        return input_path

    target_epub = Path(output_epub_path) if output_epub_path is not None else input_path.with_suffix(".epub")
    preprocessor = get_preprocessor(input_path)
    sections = preprocessor.extract_sections(input_path)
    book_title = title or input_path.stem or "Document"
    return build_epub_from_sections(sections, target_epub, title=book_title)
