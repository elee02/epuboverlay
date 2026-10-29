"""CosyVoice2-0.5B synthesizer — ultra-lightweight multilingual & emotional TTS with paralinguistic tags."""
from __future__ import annotations

import os
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
    "sft": "Preset Speaker (Built-in SFT Voice — No Reference Audio Needed)",
}

COSYVOICE_VOICES: list[dict[str, str]] = [
    {"id": "英文女", "name": "English Female (Preset SFT)"},
    {"id": "英文男", "name": "English Male (Preset SFT)"},
    {"id": "中文女", "name": "Chinese Female (Preset SFT)"},
    {"id": "中文男", "name": "Chinese Male (Preset SFT)"},
    {"id": "日语男", "name": "Japanese Male (Preset SFT)"},
    {"id": "韩语女", "name": "Korean Female (Preset SFT)"},
    {"id": "粤语女", "name": "Cantonese Female (Preset SFT)"},
]

_INLINE_INSTRUCT_RE = re.compile(r"^\s*\[instruct\s*:\s*([^\]]+)\]\s*", re.IGNORECASE)


class CosyVoice2Synthesizer(BaseSynthesizer):
    """CosyVoice2-0.5B synthesizer by FunAudioLLM.

    Supports 9 languages (English, Russian, Korean, Japanese, Chinese, German,
    Spanish, French, Italian), natural-language emotion/dialect instructions
    (``inference_instruct2``), cross-lingual voice cloning, preset SFT speakers,
    and inline paralinguistic markers such as ``[breath]``, ``[laughter]``,
    ``[sigh]``, and ``<strong>word</strong>``.
    """

    _DEFAULT_SAMPLE_RATE = 24000

    def __init__(
        self,
        model_name: str = "iic/CosyVoice2-0.5B",
        mode: str = "instruct",
        speaker: str = "英文女",
        ref_audio: str | Path | None = None,
        ref_text: str = "",
        instruct: str = "",
        language: str = "auto",
        speed: float = 1.0,
        api_url: str = "",
        device: str | None = None,
    ) -> None:
        self.model_name = (model_name or "iic/CosyVoice2-0.5B").strip()
        self.mode = (mode or "instruct").strip().lower()
        self.speaker = (speaker or "英文女").strip()
        self.ref_audio = str(ref_audio) if ref_audio else ""
        self.ref_text = (ref_text or "").strip()
        self.instruct = (instruct or "").strip()
        self.language = (language or "auto").strip().lower()
        self._speed = float(speed)
        self.api_url = (api_url or os.environ.get("COSYVOICE_API_URL", "")).strip()
        self._lock = threading.Lock()
        self.device = device or "cuda"

        if self.mode != "sft" and not self.ref_audio:
            raise ValueError(
                "ref_audio (reference voice clip) is required for CosyVoice2-0.5B "
                "in 'instruct', 'zero_shot', and 'cross_lingual' modes. "
                "Select a Reference Voice, upload/record a Reference Audio clip, or switch to 'Preset Speaker (sft)' mode."
            )

        self._model = None
        self._sample_rate = self._DEFAULT_SAMPLE_RATE
        self._prompt_speech_16k = self.ref_audio

        if not self.api_url:
            try:
                from cosyvoice.cli.cosyvoice import CosyVoice2  # type: ignore[import-not-found]
            except ImportError as e:
                raise ImportError(
                    "CosyVoice2 runtime (`cosyvoice.cli.cosyvoice`) is not found in PYTHONPATH. "
                    "Install the FunAudioLLM/CosyVoice package or set COSYVOICE_API_URL to a running CosyVoice2 server."
                ) from e

            self._model = CosyVoice2(
                self.model_name,
                load_jit=False,
                load_trt=False,
                fp16=(self.device == "cuda"),
            )
            self._sample_rate = int(
                getattr(self._model, "sample_rate", self._DEFAULT_SAMPLE_RATE) or self._DEFAULT_SAMPLE_RATE
            )

            if self.ref_audio:
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
            if self.mode == "sft" and hasattr(self._model, "inference_sft"):
                gen = self._model.inference_sft(
                    prepared_text,
                    self.speaker,
                    stream=False,
                    speed=self._speed,
                )
            elif self.mode == "instruct" and active_instruct and hasattr(self._model, "inference_instruct2"):
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
