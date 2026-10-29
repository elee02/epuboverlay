"""Supertonic-3 synthesizer: ultra-light ONNX multilingual TTS (Korean, Russian, ...).

Supertonic runs on CPU through ONNX Runtime (no PyTorch required), ships
10 preset voices and supports 30+ languages, including Korean and Russian.
"""
from __future__ import annotations

import threading

from epuboverlay.synthesizers.base import BaseSynthesizer


# Built-in preset voice styles (5 female, 5 male).
SUPERTONIC_VOICES: list[str] = [
    "F1", "F2", "F3", "F4", "F5",
    "M1", "M2", "M3", "M4", "M5",
]

# Languages exposed in the UI (the engine supports more; any ISO code accepted).
SUPERTONIC_LANGUAGES: dict[str, str] = {
    "auto": "Auto-detect",
    "ko": "Korean",
    "ru": "Russian",
    "en": "English",
    "ja": "Japanese",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "uk": "Ukrainian",
}

# The pipeline assumes a 24 kHz timeline by default, so output is resampled
# from the model's native 44.1 kHz to keep SMIL timing consistent.
_OUTPUT_SAMPLE_RATE = 24000


class SupertonicSynthesizer(BaseSynthesizer):
    """Supertonic-3 preset-voice synthesizer.

    Args:
        voice: Preset voice name (``F1``-``F5``, ``M1``-``M5``).
        language: ISO code (``ko``, ``ru``, ...) or ``"auto"`` to detect per chunk.
        speed: Speech speed factor (0.7-2.0 supported by the engine).
        total_steps: Denoising steps (quality vs. speed, 1-100, default 8).
        model: Supertonic model name (default ``supertonic-3``).
    """

    def __init__(
        self,
        voice: str = "F1",
        language: str = "auto",
        speed: float = 1.0,
        total_steps: int = 8,
        model: str = "supertonic-3",
    ) -> None:
        try:
            from supertonic import TTS  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                f"supertonic could not be imported ({e}). Please install it using "
                "'uv sync --extra supertonic' (or 'pip install \"epuboverlay[supertonic]\"') "
                "to use the SupertonicSynthesizer. If it is already installed, "
                "try: uv sync --extra supertonic --reinstall-package onnxruntime"
            ) from e

        voice = voice or "F1"
        if voice not in SUPERTONIC_VOICES:
            raise ValueError(
                f"Unknown Supertonic voice: '{voice}'. "
                f"Available voices: {', '.join(SUPERTONIC_VOICES)}"
            )

        self._tts = TTS(model=model, auto_download=True)
        self._style = self._tts.get_voice_style(voice_name=voice)
        self._voice = voice
        self._language = (language or "auto").strip().lower()
        self._speed = float(speed)
        self._total_steps = int(total_steps)
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        return _OUTPUT_SAMPLE_RATE

    @property
    def speed(self) -> float:
        return self._speed

    def _resolve_language(self, text: str) -> str:
        from epuboverlay.normalization import detect_text_language

        hint = None if self._language in ("", "auto") else self._language
        return detect_text_language(text, hint)

    def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", 0

        import numpy as np  # type: ignore[import-untyped]

        lang = self._resolve_language(text)
        with self._lock:
            wav, _duration = self._tts.synthesize(
                text,
                voice_style=self._style,
                total_steps=self._total_steps,
                speed=min(max(self._speed, 0.7), 2.0),
                lang=lang,
            )

        audio = np.asarray(wav, dtype="float32").reshape(-1)
        native_rate = int(getattr(self._tts, "sample_rate", 44100))
        if native_rate != _OUTPUT_SAMPLE_RATE:
            try:
                from math import gcd

                from scipy.signal import resample_poly  # type: ignore[import-untyped]

                g = gcd(_OUTPUT_SAMPLE_RATE, native_rate)
                audio = resample_poly(
                    audio, _OUTPUT_SAMPLE_RATE // g, native_rate // g
                ).astype("float32")
            except ImportError:
                n_out = int(round(len(audio) * _OUTPUT_SAMPLE_RATE / native_rate))
                audio = np.interp(
                    np.linspace(0, len(audio) - 1, n_out),
                    np.arange(len(audio)),
                    audio,
                ).astype("float32")

        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        return self._to_wav_bytes(pcm.tobytes(), _OUTPUT_SAMPLE_RATE), len(pcm)
