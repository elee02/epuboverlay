"""Dummy (silent) synthesizer for testing and development."""
from __future__ import annotations

import io
import wave

from epuboverlay.synthesizers.base import BaseSynthesizer


class DummySynthesizer(BaseSynthesizer):
    """A mock synthesizer that generates silent WAV bytes for testing."""

    def __init__(self, sample_rate: int = 24000, chars_per_sec: float = 15.0) -> None:
        self._sample_rate = sample_rate
        self.chars_per_sec = chars_per_sec
        self._speed = 1.0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def speed(self) -> float:
        return self._speed

    def synthesize(self, text: str) -> tuple[bytes, int]:
        duration = len(text) / self.chars_per_sec
        if duration <= 0:
            duration = 0.1

        num_samples = int(duration * self._sample_rate)
        pcm_data = b"\x00" * (num_samples * 2)

        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(self._sample_rate)
            wav_out.writeframes(pcm_data)

        return out_io.getvalue(), num_samples
