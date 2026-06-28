"""Progress reporting infrastructure for epuboverlay pipeline."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol


@dataclass(frozen=True)
class ProgressEvent:
    """Structured progress event emitted by the pipeline."""

    phase: str  # "parsing", "synthesizing", "converting", "packaging"
    chapter_index: int = 0  # current chapter (0-based)
    chapter_total: int = 0  # total chapters in spine
    chapter_name: str = ""  # idref / display name
    chunk_index: int = 0  # current chunk within chapter
    chunk_total: int = 0  # total chunks in chapter
    elapsed_seconds: float = 0.0
    message: str = ""  # human-readable status line
    synthesis_elapsed_seconds: float = 0.0
    total_chunks_to_synthesize: int = 0
    chunks_processed_so_far: int = 0
    total_characters: int = 0
    estimated_total_hours: float = 0.0
    audiobook_duration_seconds: float = 0.0

    @property
    def overall_percent(self) -> float:
        """Estimate overall completion percentage."""
        if self.chapter_total <= 0:
            return 0.0
        chapter_progress = self.chapter_index / self.chapter_total
        if self.chunk_total > 0:
            chunk_progress = self.chunk_index / self.chunk_total
        else:
            chunk_progress = 0.0
        return min((chapter_progress + chunk_progress / self.chapter_total) * 100.0, 100.0)

    @property
    def estimated_remaining_seconds(self) -> float | None:
        """Calculate faithful remaining seconds based on average time per chunk."""
        if self.phase == "done":
            return 0.0
        if self.phase in ("error", "cancelled"):
            return None
        if self.chunks_processed_so_far > 0 and self.total_chunks_to_synthesize > 0:
            if self.chunks_processed_so_far >= self.total_chunks_to_synthesize:
                return 5.0  # nominal estimate for final packaging
            avg_time_per_chunk = self.synthesis_elapsed_seconds / self.chunks_processed_so_far
            remaining_chunks = self.total_chunks_to_synthesize - self.chunks_processed_so_far
            return remaining_chunks * avg_time_per_chunk
        return None

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON transport."""
        return {
            "phase": self.phase,
            "chapter_index": self.chapter_index,
            "chapter_total": self.chapter_total,
            "chapter_name": self.chapter_name,
            "chunk_index": self.chunk_index,
            "chunk_total": self.chunk_total,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "message": self.message,
            "overall_percent": round(self.overall_percent, 1),
            "synthesis_elapsed_seconds": round(self.synthesis_elapsed_seconds, 2),
            "total_chunks_to_synthesize": self.total_chunks_to_synthesize,
            "chunks_processed_so_far": self.chunks_processed_so_far,
            "total_characters": self.total_characters,
            "estimated_total_hours": round(self.estimated_total_hours, 2),
            "audiobook_duration_seconds": round(self.audiobook_duration_seconds, 2),
            "estimated_remaining_seconds": round(self.estimated_remaining_seconds, 2) if self.estimated_remaining_seconds is not None else None,
        }


class ProgressReporter(Protocol):
    """Protocol for receiving progress events."""

    def report(self, event: ProgressEvent) -> None: ...


class ConsoleProgressReporter:
    """Prints live progress to the terminal with overwriting line."""

    def __init__(self, file=None) -> None:
        self._file = file or sys.stdout
        self._last_line_len = 0

    def report(self, event: ProgressEvent) -> None:
        if event.phase == "done":
            self._clear_line()
            print(f"\n✓ {event.message}", file=self._file, flush=True)
            return

        if event.phase == "error":
            self._clear_line()
            print(f"\n✗ {event.message}", file=self._file, flush=True)
            return

        elapsed = event.elapsed_seconds
        elapsed_str = self._format_time(elapsed)

        # Build progress line
        parts = []

        if event.chapter_total > 0:
            current_chap = min(event.chapter_index + 1, event.chapter_total)
            parts.append(
                f"[Chapter {current_chap}/{event.chapter_total}]"
            )

        if event.chunk_total > 0 and event.chunk_index < event.chunk_total:
            parts.append(
                f"[Chunk {event.chunk_index + 1}/{event.chunk_total}]"
            )

        pct = event.overall_percent
        bar_width = 20
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        parts.append(f"|{bar}| {pct:.1f}%")

        parts.append(f"Elapsed: {elapsed_str}")

        # ETA estimate
        eta_secs = event.estimated_remaining_seconds
        if eta_secs is not None:
            parts.append(f"ETA: ~{self._format_time(eta_secs)}")
        elif pct > 0:
            total_est = elapsed / (pct / 100.0)
            remaining = total_est - elapsed
            parts.append(f"ETA: ~{self._format_time(remaining)}")

        if event.chapter_name:
            parts.append(f"({event.chapter_name})")

        line = " ".join(parts)
        self._write_line(line)

    def _write_line(self, line: str) -> None:
        padding = max(self._last_line_len - len(line), 0)
        print(f"\r{line}{' ' * padding}", end="", file=self._file, flush=True)
        self._last_line_len = len(line)

    def _clear_line(self) -> None:
        print(f"\r{' ' * self._last_line_len}\r", end="", file=self._file, flush=True)
        self._last_line_len = 0

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 0:
            seconds = 0
        m = int(seconds // 60)
        s = seconds % 60
        if m >= 60:
            h = m // 60
            m = m % 60
            return f"{h}h{m:02d}m"
        return f"{m}m{s:04.1f}s"


class CallbackProgressReporter:
    """Forwards progress events to a callable — used by the web server."""

    def __init__(self, callback: Callable[[ProgressEvent], None]) -> None:
        self._callback = callback

    def report(self, event: ProgressEvent) -> None:
        self._callback(event)
