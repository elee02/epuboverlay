"""Qwen3-TTS synthesizer — multilingual emotional speech synthesis & voice design."""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from epuboverlay.synthesizers.base import BaseSynthesizer


QWEN3_MODELS: dict[str, str] = {
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice": "Qwen3-TTS 1.7B CustomVoice (Emotion Instruct + Preset Speakers)",
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice": "Qwen3-TTS 0.6B CustomVoice (Fast Preset Speakers)",
    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign": "Qwen3-TTS 1.7B VoiceDesign (Design Any Voice from Text Prompt)",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base": "Qwen3-TTS 1.7B Base (High-Fidelity 3s Zero-Shot Cloning)",
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base": "Qwen3-TTS 0.6B Base (Ultra-Fast Lightweight Zero-Shot Cloning)",
}

QWEN3_VOICES: list[dict[str, str]] = [
    {"id": "Ryan", "name": "Ryan (English Male — Dynamic & Expressive)", "gender": "Male", "lang": "EN/Multi"},
    {"id": "Aiden", "name": "Aiden (English Male — Clear & Conversational)", "gender": "Male", "lang": "EN/Multi"},
    {"id": "Serena", "name": "Serena (Warm, Gentle Female — Audiobook)", "gender": "Female", "lang": "ZH/Multi"},
    {"id": "Vivian", "name": "Vivian (Bright, Articulate Female — Narrative)", "gender": "Female", "lang": "ZH/Multi"},
    {"id": "Uncle_Fu", "name": "Uncle Fu (Deep, Resonant Male — Storytelling)", "gender": "Male", "lang": "ZH/Multi"},
    {"id": "Dylan", "name": "Dylan (Natural, Youthful Male)", "gender": "Male", "lang": "ZH/Multi"},
    {"id": "Eric", "name": "Eric (Lively, Warm Male)", "gender": "Male", "lang": "ZH/Multi"},
    {"id": "Ono_Anna", "name": "Ono Anna (Crisp Japanese/Multi Female)", "gender": "Female", "lang": "JA/Multi"},
    {"id": "Sohee", "name": "Sohee (Emotive Korean/Multi Female)", "gender": "Female", "lang": "KO/Multi"},
]

QWEN3_LANGUAGES: dict[str, str] = {
    "auto": "Auto-Detect Language",
    "en": "English",
    "ru": "Russian (Русский)",
    "ko": "Korean (한국어)",
    "ja": "Japanese (日本語)",
    "zh": "Chinese (中文)",
    "de": "German (Deutsch)",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "it": "Italian (Italiano)",
    "pt": "Portuguese (Português)",
}

_LANG_ISO_TO_NAME: dict[str, str] = {
    "": "Auto",
    "auto": "Auto",
    "en": "English",
    "english": "English",
    "ru": "Russian",
    "russian": "Russian",
    "ko": "Korean",
    "korean": "Korean",
    "ja": "Japanese",
    "jp": "Japanese",
    "japanese": "Japanese",
    "zh": "Chinese",
    "chinese": "Chinese",
    "de": "German",
    "german": "German",
    "es": "Spanish",
    "spanish": "Spanish",
    "fr": "French",
    "french": "French",
    "it": "Italian",
    "italian": "Italian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
}

_VALID_SPEAKERS_MAP: dict[str, str] = {v["id"].lower(): v["id"] for v in QWEN3_VOICES}

_INLINE_INSTRUCT_RE = re.compile(r"^\s*\[instruct\s*:\s*([^\]]+)\]\s*", re.IGNORECASE)


def normalize_qwen_language(lang: str | None) -> str:
    """Normalize ISO code or language name to Qwen3-TTS language identifier."""
    if not lang:
        return "Auto"
    cleaned = lang.strip().lower()
    return _LANG_ISO_TO_NAME.get(cleaned, lang.strip().capitalize())


class Qwen3TTSSynthesizer(BaseSynthesizer):
    """Qwen3-TTS synthesizer supporting natural-language emotion/intonation instructions,
    text-to-voice design, and 3-second zero-shot voice cloning across 10 languages
    (English, Russian, Korean, Japanese, Chinese, German, Spanish, French, Italian, Portuguese).

    Modes:
        - ``custom_voice``: Uses a built-in speaker (e.g. ``"Ryan"``, ``"Serena"``) with
          an optional natural-language ``instruct`` prompt for granular emotion & intonation.
        - ``voice_design``: Synthesizes a brand-new speaker identity and emotional delivery
          purely from a natural-language ``instruct`` description.
        - ``clone``: Clones a voice from a 3-10s ``ref_audio`` file (and optional ``ref_text``).
    """

    _DEFAULT_SAMPLE_RATE = 24000

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        mode: str = "custom_voice",
        speaker: str = "Ryan",
        instruct: str = "",
        language: str = "Auto",
        ref_audio: str | Path | None = None,
        ref_text: str = "",
        speed: float = 1.0,
        temp: float = 0.7,
        device: str | None = None,
    ) -> None:
        try:
            import qwen_tts  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "qwen-tts is not installed. Please install it using "
                "'uv sync --extra qwen' (or 'pip install \"epuboverlay[qwen]\"') "
                "to use the Qwen3TTSSynthesizer."
            ) from e

        self.mode = (mode or "custom_voice").strip().lower()
        raw_model = (model_name or "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice").strip()

        # Ensure checkpoint matches selected synthesis mode
        if self.mode == "clone" and "base" not in raw_model.lower():
            raw_model = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
        elif self.mode == "voice_design" and "voicedesign" not in raw_model.lower():
            raw_model = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        elif self.mode == "custom_voice" and "customvoice" not in raw_model.lower():
            raw_model = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
        self.model_name = raw_model

        raw_speaker = (speaker or "Ryan").strip()
        self.speaker = _VALID_SPEAKERS_MAP.get(raw_speaker.lower(), "Ryan")
        self.instruct = (instruct or "").strip()
        self.language = normalize_qwen_language(language)
        self.ref_audio = str(ref_audio) if ref_audio else ""
        self.ref_text = (ref_text or "").strip()
        self._speed = float(speed)
        self.temp = float(temp)
        self._lock = threading.Lock()
        self._sample_rate = self._DEFAULT_SAMPLE_RATE
        self._voice_clone_prompt: Any = None

        if self.mode == "clone" and not self.ref_audio:
            raise ValueError("ref_audio is required for Qwen3-TTS 'clone' mode.")
        if self.mode == "voice_design" and not self.instruct:
            self.instruct = "A warm, articulate narrator with natural, engaging intonation."

        if device is None or device == "":
            try:
                import torch
                device = (
                    "cuda"
                    if torch.cuda.is_available()
                    else "mps"
                    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
                    else "cpu"
                )
            except ImportError:
                device = "cpu"
        self.device = device

        # Initialize Qwen3-TTS model wrapper
        model_cls = getattr(qwen_tts, "Qwen3TTSModel", None) or getattr(qwen_tts, "QwenTTS", None)
        if model_cls is not None:
            if hasattr(model_cls, "from_pretrained"):
                self._model = model_cls.from_pretrained(self.model_name, device_map=self.device)
            else:
                self._model = model_cls(model_name=self.model_name, device=self.device)
        else:
            raise RuntimeError("Compatible Qwen3TTSModel entry point not found in 'qwen_tts'.")

        # Precompute voice clone prompt once so multi-chunk books don't re-encode ref_audio per sentence
        if self.mode == "clone" and self.ref_audio and hasattr(self._model, "create_voice_clone_prompt"):
            try:
                self._voice_clone_prompt = self._model.create_voice_clone_prompt(
                    ref_audio=self.ref_audio,
                    ref_text=self.ref_text or None,
                    x_vector_only_mode=not bool(self.ref_text),
                )
            except Exception:
                self._voice_clone_prompt = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def speed(self) -> float:
        return self._speed

    def _extract_inline_instruct(self, text: str) -> tuple[str, str]:
        match = _INLINE_INSTRUCT_RE.match(text)
        if match:
            return match.group(1).strip(), text[match.end():].strip()
        return self.instruct, text

    def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", 0

        import numpy as np  # type: ignore[import-untyped]

        active_instruct, clean_text = self._extract_inline_instruct(text)
        if not clean_text.strip():
            return b"", 0

        lang_arg = self.language or "Auto"

        with self._lock:
            audio, sr = self._invoke_model(clean_text, active_instruct, lang_arg)
            if sr and int(sr) > 0:
                self._sample_rate = int(sr)

        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        elif hasattr(audio, "numpy"):
            audio = audio.numpy()
        audio = np.asarray(audio, dtype="float32").squeeze()

        if audio.size == 0:
            return b"", 0

        if abs(self._speed - 1.0) > 0.01:
            from scipy.signal import resample  # type: ignore[import-untyped]
            new_len = int(len(audio) / self._speed)
            if new_len > 0:
                audio = resample(audio, new_len).astype("float32")

        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767.0).astype(np.int16)
        return self._to_wav_bytes(audio_int16.tobytes(), self._sample_rate), len(audio_int16)

    def _invoke_model(
        self,
        text: str,
        instruct: str,
        language: str,
    ) -> tuple[object, int]:
        """Dispatch to the appropriate Qwen3-TTS generation method."""
        if self.mode == "clone" and hasattr(self._model, "generate_voice_clone"):
            clone_kwargs: dict[str, Any] = {
                "text": text,
                "language": language,
                "temperature": self.temp,
            }
            if self._voice_clone_prompt is not None:
                clone_kwargs["voice_clone_prompt"] = self._voice_clone_prompt
            else:
                clone_kwargs["ref_audio"] = self.ref_audio
                clone_kwargs["ref_text"] = self.ref_text or None
                clone_kwargs["x_vector_only_mode"] = not bool(self.ref_text)
            res = self._model.generate_voice_clone(**clone_kwargs)
        elif self.mode == "voice_design" and hasattr(self._model, "generate_voice_design"):
            res = self._model.generate_voice_design(
                text=text,
                language=language,
                instruct=instruct or "A clear, expressive audiobook narrator.",
                temperature=self.temp,
            )
        elif hasattr(self._model, "generate_custom_voice"):
            res = self._model.generate_custom_voice(
                text=text,
                language=language,
                speaker=self.speaker or "Ryan",
                instruct=instruct or None,
                temperature=self.temp,
            )
        elif hasattr(self._model, "synthesize"):
            res = self._model.synthesize(
                text=text,
                speaker=self.speaker,
                instruct=instruct,
                language=language,
                ref_audio=self.ref_audio or None,
                ref_text=self.ref_text or None,
            )
        else:
            res = self._model(text)

        if isinstance(res, tuple) and len(res) >= 2:
            wavs, sr = res[0], int(res[1])
            if isinstance(wavs, list) and len(wavs) > 0:
                return wavs[0], sr
            return wavs, sr
        return res, self._DEFAULT_SAMPLE_RATE
