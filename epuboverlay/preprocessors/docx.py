from __future__ import annotations

from pathlib import Path
from typing import List

from epuboverlay.preprocessors.base import BasePreprocessor, DocumentSection


class DOCXPreprocessor(BasePreprocessor):
    """Placeholder preprocessor for Microsoft Word (.docx) files."""
    
    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".docx"
        
    def extract_sections(self, file_path: Path) -> List[DocumentSection]:
        try:
            import docx
            doc = docx.Document(file_path)
            sections: List[DocumentSection] = []
            current_title = "Document Body"
            current_paras = []
            sec_idx = 0
            
            for p in doc.paragraphs:
                if p.style.name.startswith("Heading"):
                    text_so_far = "\n".join(current_paras).strip()
                    if text_so_far:
                        sections.append(DocumentSection(
                            id=f"docx_sec_{sec_idx}",
                            title=current_title,
                            text_content=text_so_far,
                            char_count=len(text_so_far),
                            preview=text_so_far[:1000]
                        ))
                        sec_idx += 1
                    current_title = p.text.strip()
                    current_paras = []
                else:
                    if p.text.strip():
                        current_paras.append(p.text.strip())
                        
            text_so_far = "\n".join(current_paras).strip()
            if text_so_far:
                sections.append(DocumentSection(
                    id=f"docx_sec_{sec_idx}",
                    title=current_title,
                    text_content=text_so_far,
                    char_count=len(text_so_far),
                    preview=text_so_far[:1000]
                ))
            return sections
        except ImportError:
            filename = file_path.name
            dummy_text = f"This is a placeholder for the DOCX file '{filename}'. Please install 'docx' to enable full extraction."
            return [DocumentSection(
                id="docx_placeholder",
                title="DOCX Content",
                text_content=dummy_text,
                char_count=len(dummy_text),
                preview=dummy_text
            )]
