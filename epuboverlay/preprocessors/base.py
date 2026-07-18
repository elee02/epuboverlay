from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

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
