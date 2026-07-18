from __future__ import annotations

from pathlib import Path
from typing import List

from epuboverlay.preprocessors.base import BasePreprocessor, DocumentSection


class PDFPreprocessor(BasePreprocessor):
    """Placeholder preprocessor for PDF files (can handle in future with pypdf)."""
    
    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".pdf"
        
    def extract_sections(self, file_path: Path) -> List[DocumentSection]:
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            sections: List[DocumentSection] = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                clean_text = text.strip()
                if clean_text:
                    sections.append(DocumentSection(
                        id=f"page_{i+1}",
                        title=f"Page {i+1}",
                        text_content=clean_text,
                        char_count=len(clean_text),
                        preview=clean_text[:1000]
                    ))
            return sections
        except ImportError:
            filename = file_path.name
            dummy_text = f"This is a placeholder for the PDF file '{filename}'. Please install 'pypdf' to enable full extraction."
            return [DocumentSection(
                id="pdf_placeholder",
                title="PDF Content",
                text_content=dummy_text,
                char_count=len(dummy_text),
                preview=dummy_text
            )]
