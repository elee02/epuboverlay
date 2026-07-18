from __future__ import annotations

from pathlib import Path

from epuboverlay.preprocessors.base import BasePreprocessor, DocumentSection, ends_with_terminal_punctuation
from epuboverlay.preprocessors.epub import EPUBPreprocessor, preprocess_epub_workspace, merge_consecutive_paragraphs, split_xhtml_by_anchors
from epuboverlay.preprocessors.pdf import PDFPreprocessor
from epuboverlay.preprocessors.docx import DOCXPreprocessor
from epuboverlay.preprocessors.markdown import MarkdownPreprocessor
from epuboverlay.preprocessors.txt import TXTPreprocessor

__all__ = [
    "BasePreprocessor",
    "DocumentSection",
    "ends_with_terminal_punctuation",
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
