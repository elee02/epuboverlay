"""Base synthesizer interface for epuboverlay TTS backends."""
from __future__ import annotations

import io
import wave
from abc import ABC, abstractmethod
from typing import Protocol


class FrameTimedSynthesizer(Protocol):
    """Synthesizer that exposes output frame lengths per generated chunk."""

    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Return encoded audio bytes and generated frame count for the chunk."""


class BaseSynthesizer(ABC):
    """Abstract base class for all TTS synthesizer backends.

    All synthesizers must implement ``synthesize()`` and declare their
    ``sample_rate`` and ``speed`` properties.
    """

    @abstractmethod
    def synthesize(self, text: str) -> tuple[bytes, int]:
        """Synthesize *text* and return ``(wav_bytes, frame_count)``."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Audio sample rate in Hz (e.g. 24000)."""

    @property
    @abstractmethod
    def speed(self) -> float:
        """Speech speed factor (1.0 = normal)."""

    # ── Shared utility ───────────────────────────────────────────────

    @staticmethod
    def _to_wav_bytes(pcm_int16_bytes: bytes, sample_rate: int) -> bytes:
        """Wrap raw PCM-16 bytes in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_int16_bytes)
        return buf.getvalue()
