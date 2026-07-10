"""PocketTTS synthesizer — lightweight CPU-efficient zero-shot voice cloning."""
from __future__ import annotations

import io
import wave
from pathlib import Path

from epuboverlay.synthesizers.base import BaseSynthesizer


class PocketSynthesizer(BaseSynthesizer):
    """PocketTTS synthesizer — ~100M parameter zero-shot voice cloner by Kyutai Labs.

    Runs at ~6x real-time on CPU.  The voice state is pre-computed from the
    reference audio file once at startup and cached for all subsequent calls.

    Args:
        ref_audio: Path to a reference audio file (.wav) for voice cloning.
        speed: Speech speed factor (default 1.0).
    """

    _SAMPLE_RATE = 24000

    def __init__(
        self,
        ref_audio: str | Path,
        speed: float = 1.0,
    ) -> None:
        try:
            from pocket_tts import TTSModel  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "pocket-tts is not installed. Please install it using "
                "'pip install pocket-tts' to use the PocketSynthesizer."
            ) from e

        self.ref_audio = str(ref_audio)
        self._speed = speed

        # Load model and pre-compute voice state once
        self._model = TTSModel.load_model()
        self._voice_state = self._model.get_state_for_audio_prompt(self.ref_audio)

    @property
    def sample_rate(self) -> int:
        return self._SAMPLE_RATE

    @property
    def speed(self) -> float:
        return self._speed

    def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", 0

        import numpy as np  # type: ignore[import-untyped]

        # Generate audio tensor
        audio = self._model.generate_audio(self._voice_state, text)

        # Convert to numpy if needed
        if hasattr(audio, "numpy"):
            audio = audio.numpy()
        audio = np.asarray(audio, dtype="float32").squeeze()

        if audio.size == 0:
            return b"", 0

        # Apply speed scaling via resampling if speed != 1.0
        if abs(self._speed - 1.0) > 0.01:
            from scipy.signal import resample  # type: ignore[import-untyped]
            original_len = len(audio)
            new_len = int(original_len / self._speed)
            if new_len > 0:
                audio = resample(audio, new_len).astype("float32")

        # Convert float32 → int16 PCM
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767.0).astype(np.int16)

        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

        return out_io.getvalue(), len(audio_int16)
