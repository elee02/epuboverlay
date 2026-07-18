from __future__ import annotations

import re
from pathlib import Path
from typing import List

from epuboverlay.preprocessors.base import BasePreprocessor, DocumentSection


class TXTPreprocessor(BasePreprocessor):
    """Preprocessor for plain text (.txt) documents."""
    
    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".txt"
        
    def extract_sections(self, file_path: Path) -> List[DocumentSection]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        
        # Split by obvious dividers: double empty lines, "Chapter X" pattern, etc.
        # Let's search for "Chapter X" or "Section X" headers or fall back to 10k character blocks
        lines = text.split("\n")
        sections: List[DocumentSection] = []
        
        current_title = "Introduction"
        current_lines = []
        sec_counter = 0
        
        for line in lines:
            line_stripped = line.strip()
            # Recognize "Chapter X", "Chapter Name", or "Section X" pattern
            is_header = False
            if re.match(r"^(Chapter|Section|Act|Part)\s+\d+", line_stripped, re.I):
                is_header = True
            elif len(line_stripped) < 60 and line_stripped.isupper() and len(line_stripped) > 3:
                # Short uppercase lines could be chapter titles
                is_header = True
                
            if is_header and (current_lines or sec_counter > 0):
                # Flush previous section
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
                
                current_title = line_stripped
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
            
        # Fallback to chunking by size if it's just one massive block
        if len(sections) == 1 and sections[0].char_count > 15000:
            original_text = sections[0].text_content
            sections.clear()
            chunk_size = 10000
            for k in range(0, len(original_text), chunk_size):
                chunk = original_text[k : k + chunk_size]
                sec_id = f"chunk_{k // chunk_size}"
                sections.append(DocumentSection(
                    id=sec_id,
                    title=f"Part {k // chunk_size + 1}",
                    text_content=chunk,
                    char_count=len(chunk),
                    preview=chunk[:1000]
                ))
                
        return sections
