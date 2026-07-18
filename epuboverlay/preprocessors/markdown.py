from __future__ import annotations

import re
from pathlib import Path
from typing import List

from epuboverlay.preprocessors.base import BasePreprocessor, DocumentSection


class MarkdownPreprocessor(BasePreprocessor):
    """Preprocessor for Markdown (.md) documents."""
    
    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in (".md", ".markdown")
        
    def extract_sections(self, file_path: Path) -> List[DocumentSection]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        
        # Split by heading tags (# H1, ## H2)
        lines = text.split("\n")
        sections: List[DocumentSection] = []
        
        current_title = "Introduction"
        current_lines = []
        sec_counter = 0
        
        for line in lines:
            match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
            if match:
                # Save previous section
                sec_text = "\n".join(current_lines).strip()
                if sec_text:
                    sec_id = f"section_{sec_counter}"
                    sections.append(DocumentSection(
                        id=sec_id,
                        title=current_title,
                        text_content=sec_text,
                        char_count=len(sec_text),
                        preview=sec_text[:1000]
                    ))
                    sec_counter += 1
                
                # Start new section
                current_title = match.group(2).strip()
                current_lines = []
            else:
                current_lines.append(line)
                
        # Final section
        sec_text = "\n".join(current_lines).strip()
        if sec_text:
            sec_id = f"section_{sec_counter}"
            sections.append(DocumentSection(
                id=sec_id,
                title=current_title,
                text_content=sec_text,
                char_count=len(sec_text),
                preview=sec_text[:1000]
            ))
            
        return sections
