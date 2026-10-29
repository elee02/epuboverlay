"""CosyVoice2-0.5B synthesizer — ultra-lightweight multilingual & emotional TTS with paralinguistic tags."""
from __future__ import annotations

import re
import threading
from pathlib import Path

from epuboverlay.synthesizers.base import BaseSynthesizer


COSYVOICE_LANGUAGES: dict[str, str] = {
    "auto": "Auto-Detect / Native Script",
    "en": "English (<|en|>)",
    "ru": "Russian / Русский (<|ru|>)",
    "ko": "Korean / 한국어 (<|ko|>)",
    "ja": "Japanese / 日本語 (<|jp|>)",
    "zh": "Chinese / 中文 (<|zh|>)",
    "de": "German / Deutsch (<|de|>)",
    "es": "Spanish / Español (<|es|>)",
    "fr": "French / Français (<|fr|>)",
    "it": "Italian / Italiano (<|it|>)",
}

COSYVOICE_LANG_TOKENS: dict[str, str] = {
    "en": "<|en|>",
    "ru": "<|ru|>",
    "ko": "<|ko|>",
    "ja": "<|jp|>",
    "zh": "<|zh|>",
    "de": "<|de|>",
    "es": "<|es|>",
    "fr": "<|fr|>",
    "it": "<|it|>",
}

COSYVOICE_MODES: dict[str, str] = {
    "instruct": "Instruct + Emotion Control (Natural-Language Style + Reference Audio)",
    "zero_shot": "Zero-Shot Cloning (Reference Audio + Transcript)",
    "cross_lingual": "Cross-Lingual Cloning (Clone Voice Across Any Target Language)",
}

_INLINE_INSTRUCT_RE = re.compile(r"^\s*\[instruct\s*:\s*([^\]]+)\]\s*", re.IGNORECASE)


class CosyVoice2Synthesizer(BaseSynthesizer):
    """CosyVoice2-0.5B synthesizer by FunAudioLLM.

    Supports 9 languages (English, Russian, Korean, Japanese, Chinese, German,
    Spanish, French, Italian), natural-language emotion/dialect instructions
    (``inference_instruct2``), cross-lingual voice cloning, and inline paralinguistic
    markers such as ``[breath]``, ``[laughter]``, ``[sigh]``, and ``<strong>word</strong>``.
    """

    _DEFAULT_SAMPLE_RATE = 24000

    def __init__(
        self,
        model_name: str = "iic/CosyVoice2-0.5B",
        mode: str = "instruct",
        ref_audio: str | Path | None = None,
        ref_text: str = "",
        instruct: str = "",
        language: str = "auto",
        speed: float = 1.0,
        device: str | None = None,
    ) -> None:
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice2  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "cosyvoice is not installed. Please install CosyVoice2 dependencies using "
                "'uv add \"epuboverlay[cosyvoice]\"' (or 'pip install \"epuboverlay[cosyvoice]\"') "
                "to use the CosyVoice2Synthesizer."
            ) from e

        if not ref_audio:
            raise ValueError(
                "ref_audio (reference voice clip) is required for CosyVoice2-0.5B."
            )

        self.model_name = (model_name or "iic/CosyVoice2-0.5B").strip()
        self.mode = (mode or "instruct").strip().lower()
        self.ref_audio = str(ref_audio)
        self.ref_text = (ref_text or "").strip()
        self.instruct = (instruct or "").strip()
        self.language = (language or "auto").strip().lower()
        self._speed = float(speed)
        self._lock = threading.Lock()
        self.device = device or "cuda"

        self._model = CosyVoice2(self.model_name, load_jit=False, load_trt=False, fp16=(self.device == "cuda"))
        self._sample_rate = int(getattr(self._model, "sample_rate", self._DEFAULT_SAMPLE_RATE) or self._DEFAULT_SAMPLE_RATE)

        # Load 16kHz prompt speech once
        try:
            from cosyvoice.utils.file_utils import load_wav  # type: ignore[import-not-found]
            self._prompt_speech_16k = load_wav(self.ref_audio, 16000)
        except Exception:
            self._prompt_speech_16k = self.ref_audio

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def speed(self) -> float:
        return self._speed

    def _prepare_text(self, text: str) -> tuple[str, str]:
        active_instruct = self.instruct
        match = _INLINE_INSTRUCT_RE.match(text)
        if match:
            active_instruct = match.group(1).strip()
            text = text[match.end():].strip()

        lang_token = COSYVOICE_LANG_TOKENS.get(self.language, "")
        if lang_token and not text.startswith("<|"):
            text = f"{lang_token}{text}"
        return active_instruct, text

    def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", 0

        import numpy as np  # type: ignore[import-untyped]

        active_instruct, prepared_text = self._prepare_text(text)
        if not prepared_text.strip():
            return b"", 0

        segments: list[np.ndarray] = []
        with self._lock:
            if self.mode == "instruct" and active_instruct and hasattr(self._model, "inference_instruct2"):
                gen = self._model.inference_instruct2(
                    prepared_text,
                    active_instruct,
                    self._prompt_speech_16k,
                    stream=False,
                    speed=self._speed,
                )
            elif self.mode == "zero_shot" and self.ref_text and hasattr(self._model, "inference_zero_shot"):
                gen = self._model.inference_zero_shot(
                    prepared_text,
                    self.ref_text,
                    self._prompt_speech_16k,
                    stream=False,
                    speed=self._speed,
                )
            elif hasattr(self._model, "inference_cross_lingual"):
                gen = self._model.inference_cross_lingual(
                    prepared_text,
                    self._prompt_speech_16k,
                    stream=False,
                    speed=self._speed,
                )
            else:
                gen = self._model.inference_zero_shot(
                    prepared_text,
                    self.ref_text,
                    self._prompt_speech_16k,
                    stream=False,
                )

            for chunk_out in gen:
                speech = chunk_out.get("tts_speech") if isinstance(chunk_out, dict) else chunk_out
                if hasattr(speech, "detach"):
                    speech = speech.detach().cpu().numpy()
                elif hasattr(speech, "numpy"):
                    speech = speech.numpy()
                arr = np.asarray(speech, dtype="float32").squeeze()
                if arr.size > 0:
                    segments.append(arr)

        if not segments:
            return b"", 0

        audio = np.concatenate(segments) if len(segments) > 1 else segments[0]
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767.0).astype(np.int16)
        return self._to_wav_bytes(audio_int16.tobytes(), self._sample_rate), len(audio_int16)

