"""Fish-Speech-1.5 (OpenAudio-S1-Mini) synthesizer — 8-language emotional TTS including Arabic, Russian, and Korean."""
from __future__ import annotations

import io
import json
import os
import threading
import urllib.request
import wave
from pathlib import Path

from epuboverlay.synthesizers.base import BaseSynthesizer


FISH_LANGUAGES: dict[str, str] = {
    "auto": "Auto-Detect Language",
    "en": "English",
    "ru": "Russian (Русский)",
    "ko": "Korean (한국어)",
    "ja": "Japanese (日本語)",
    "zh": "Chinese (中文)",
    "de": "German (Deutsch)",
    "es": "Spanish (Español)",
    "ar": "Arabic (العربية)",
}

FISH_EMOTION_TAGS: list[dict[str, str]] = [
    {"tag": "", "label": "Neutral / Natural Delivery"},
    {"tag": "(soft tone)", "label": "(soft tone) — Intimate & Warm"},
    {"tag": "(excited)", "label": "(excited) — Energetic & Vivid"},
    {"tag": "(sad)", "label": "(sad) — Melancholic & Somber"},
    {"tag": "(angry)", "label": "(angry) — Intense & Fierce"},
    {"tag": "(whispering)", "label": "(whispering) — Hushed Whisper"},
    {"tag": "(empathetic)", "label": "(empathetic) — Compassionate"},
    {"tag": "(serious)", "label": "(serious) — Authoritative & Grave"},
    {"tag": "(in a hurry tone)", "label": "(in a hurry tone) — Urgent Pacing"},
    {"tag": "(sighing)", "label": "(sighing) — Expressive Sigh"},
    {"tag": "(laughing)", "label": "(laughing) — Lighthearted Chuckle"},
]


class FishSpeechSynthesizer(BaseSynthesizer):
    """Fish-Speech-1.5 / OpenAudio-S1-Mini synthesizer.

    Natively supports all 8 target languages (English, Russian, Korean, Japanese,
    Chinese, German, Spanish, and Arabic), zero-shot voice cloning, and inline
    emotional & paralinguistic markers such as ``(excited)``, ``(sad)``,
    ``(whispering)``, ``(soft tone)``, and ``(sighing)``.

    Supports three execution backends:
    1. **Local Fish-Speech API Server** (``api_url``, e.g. ``http://127.0.0.1:8080/v1/tts``)
       — works out-of-the-box with a running Fish-Speech / OpenAudio server.
    2. **Fish Audio SDK** (``fish_audio_sdk``) when installed in the environment.
    3. **Direct Python Engine** (``fish_speech`` package) when installed in the environment.
    """

    _DEFAULT_SAMPLE_RATE = 44100

    def __init__(
        self,
        ref_audio: str | Path | None = None,
        ref_text: str = "",
        emotion_tag: str = "",
        language: str = "auto",
        temp: float = 0.7,
        top_p: float = 0.7,
        repetition_penalty: float = 1.2,
        speed: float = 1.0,
        api_url: str = "",
        api_key: str = "",
        device: str | None = None,
    ) -> None:
        self.ref_audio = str(ref_audio) if ref_audio else ""
        self.ref_text = (ref_text or "").strip()
        self.emotion_tag = (emotion_tag or "").strip()
        self.language = (language or "auto").strip().lower()
        self.temp = float(temp)
        self.top_p = float(top_p)
        self.repetition_penalty = float(repetition_penalty)
        self._speed = float(speed)
        self.api_url = (api_url or os.environ.get("FISH_SPEECH_API_URL", "")).strip()
        self.api_key = (api_key or os.environ.get("FISH_API_KEY", "")).strip()
        self.device = device or "cuda"
        self._lock = threading.Lock()
        self._sample_rate = self._DEFAULT_SAMPLE_RATE
        self._engine = None
        self._sdk_available = False

        try:
            import fish_speech  # type: ignore[import-not-found]
            self._engine = fish_speech
        except ImportError:
            try:
                import fish_audio_sdk  # type: ignore[import-not-found]  # noqa: F401
                self._sdk_available = True
            except ImportError:
                pass

        self._ref_audio_bytes: bytes = b""
        if self.ref_audio and Path(self.ref_audio).exists():
            self._ref_audio_bytes = Path(self.ref_audio).read_bytes()

        # Pre-encode API reference payload & cache SDK Session for zero per-chunk overhead
        self._api_references: list[dict[str, str]] = []
        if self._ref_audio_bytes:
            import base64
            self._api_references.append(
                {
                    "audio": base64.b64encode(self._ref_audio_bytes).decode("ascii"),
                    "text": self.ref_text or "",
                }
            )
        self._sdk_session = None
        self._sdk_refs: list = []
        effective_key = self.api_key or os.environ.get("FISH_API_KEY", "")
        if self._sdk_available and effective_key:
            try:
                from fish_audio_sdk import ReferenceAudio, Session  # type: ignore[import-not-found]
                self._sdk_session = Session(effective_key)
                if self._ref_audio_bytes:
                    self._sdk_refs = [ReferenceAudio(audio=self._ref_audio_bytes, text=self.ref_text or "")]
            except Exception:
                self._sdk_session = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def speed(self) -> float:
        return self._speed

    def _apply_emotion_tag(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if self.emotion_tag and not text.startswith("("):
            return f"{self.emotion_tag} {text}"
        return text

    def synthesize(self, text: str) -> tuple[bytes, int]:
        tagged_text = self._apply_emotion_tag(text)
        if not tagged_text:
            return b"", 0

        import numpy as np  # type: ignore[import-untyped]

        with self._lock:
            # 1. Custom URL / Local Server specified
            if self.api_url:
                wav_bytes = self._synthesize_via_api(tagged_text, url=self.api_url)
                return self._postprocess_wav_bytes(wav_bytes)

            # 2. Local Python package engine if available
            if self._engine is not None and hasattr(self._engine, "synthesize"):
                res = self._engine.synthesize(
                    text=tagged_text,
                    ref_audio=self.ref_audio or None,
                    ref_text=self.ref_text or None,
                    temperature=self.temp,
                    top_p=self.top_p,
                    repetition_penalty=self.repetition_penalty,
                    device=self.device,
                )
                if isinstance(res, bytes):
                    return self._postprocess_wav_bytes(res)
                if isinstance(res, tuple) and len(res) >= 2:
                    arr, sr = np.asarray(res[0], dtype="float32").squeeze(), int(res[1])
                    self._sample_rate = sr
                    if abs(self._speed - 1.0) > 0.01 and arr.size > 0:
                        from scipy.signal import resample  # type: ignore[import-untyped]
                        arr = resample(arr, max(1, int(len(arr) / self._speed))).astype("float32")
                    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16)
                    return self._to_wav_bytes(pcm.tobytes(), self._sample_rate), len(pcm)

            # 3. Fish Audio Cloud API via official SDK
            effective_key = self.api_key or os.environ.get("FISH_API_KEY", "")
            if self._sdk_available and effective_key:
                from fish_audio_sdk import ReferenceAudio, Session, TTSRequest  # type: ignore[import-not-found]

                if self._sdk_session is None:
                    self._sdk_session = Session(effective_key)
                    if self._ref_audio_bytes and not self._sdk_refs:
                        self._sdk_refs = [ReferenceAudio(audio=self._ref_audio_bytes, text=self.ref_text or "")]
                req = TTSRequest(
                    text=tagged_text,
                    references=self._sdk_refs,
                    format="wav",
                    temperature=self.temp,
                    top_p=self.top_p,
                    repetition_penalty=self.repetition_penalty,
                )
                chunks: list[bytes] = list(self._sdk_session.tts(req))
                return self._postprocess_wav_bytes(b"".join(chunks))

            # 4. Fallback to default local server port 8080 if running
            default_url = "http://127.0.0.1:8080/v1/tts"
            try:
                wav_bytes = self._synthesize_via_api(tagged_text, url=default_url)
                return self._postprocess_wav_bytes(wav_bytes)
            except Exception as e:
                raise RuntimeError(
                    "Fish-Speech is not configured: No Fish Audio API Key provided, and no local Fish-Speech server is running on http://127.0.0.1:8080/v1/tts.\n"
                    "To use Fish-Speech, either:\n"
                    "1. Enter your Fish Audio API Key in Settings (get a free key at https://fish.audio/go-api), or\n"
                    "2. Start your local Fish-Speech server on port 8080 (python tools/api_server.py --listen 127.0.0.1:8080)."
                ) from e

    def _synthesize_via_api(self, text: str, url: str | None = None) -> bytes:
        target_url = url or self.api_url
        if not target_url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid Fish-Speech API URL: {target_url}")

        payload = {
            "text": text,
            "references": self._api_references,
            "format": "wav",
            "temperature": self.temp,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
        }
        headers = {"Content-Type": "application/json"}
        effective_key = self.api_key or os.environ.get("FISH_API_KEY", "")
        if effective_key:
            headers["Authorization"] = f"Bearer {effective_key}"

        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Fish-Speech server at {target_url}: {e}"
            ) from e

    def _postprocess_wav_bytes(self, wav_bytes: bytes) -> tuple[bytes, int]:
        if not wav_bytes:
            return b"", 0
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw_frames = wf.readframes(n_frames)
            sampwidth = wf.getsampwidth()
            channels = wf.getnchannels()

        self._sample_rate = sr
        if abs(self._speed - 1.0) <= 0.01 and channels == 1 and sampwidth == 2:
            return wav_bytes, n_frames

        import numpy as np  # type: ignore[import-untyped]
        from scipy.signal import resample  # type: ignore[import-untyped]

        audio = np.frombuffer(raw_frames, dtype=np.int16).astype("float32") / 32767.0
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        if abs(self._speed - 1.0) > 0.01 and audio.size > 0:
            new_len = max(1, int(len(audio) / self._speed))
            audio = resample(audio, new_len).astype("float32")
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        return self._to_wav_bytes(pcm.tobytes(), self._sample_rate), len(pcm)
