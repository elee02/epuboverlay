"""PocketTTS synthesizer — lightweight CPU-efficient zero-shot voice cloning with granular acoustic controls."""
from __future__ import annotations

import io
import re
import threading
import wave
from pathlib import Path

from epuboverlay.synthesizers.base import BaseSynthesizer


# Built-in preset voices shipped with pocket_tts.
# Primary voices come from VCTK, Expresso, EARS, and community donations.
POCKET_VOICES: list[str] = [
    # Primary presets
    "alba", "marius", "javert", "jean", "fantine",
    "cosette", "eponine", "azelma",
    # Extended presets
    "anna", "vera", "charles", "paul", "george",
    "mary", "jane", "michael", "eve",
]

# Built-in language / flow-matching configurations bundled in pocket_tts.
POCKET_LANGUAGES: dict[str, str] = {
    "english": "English (Default)",
    "english_2026-04": "English (2026-04 Enhanced)",
    "german_24l": "German (24-Layer Multilingual)",
    "spanish_24l": "Spanish (24-Layer Multilingual)",
    "french_24l": "French (24-Layer Multilingual)",
    "italian_24l": "Italian (24-Layer Multilingual)",
    "portuguese_24l": "Portuguese (24-Layer Multilingual)",
}

_INLINE_VOICE_RE = re.compile(r"^\s*\[(?:voice|emotion)\s*:\s*([A-Za-z0-9_.-]+)\]\s*", re.IGNORECASE)
_QUOTED_DIALOGUE_RE = re.compile(r'^\s*["“«](.+)["”»]\s*$')


class PocketSynthesizer(BaseSynthesizer):
    """PocketTTS synthesizer — ~100M parameter zero-shot voice cloner by Kyutai Labs.

    Runs at ~6x real-time on CPU. Supports two primary voice modes plus granular
    acoustic / flow-matching parameters and dynamic dialogue voice switching:

    1. **Preset voice** — pass ``voice`` with a built-in name (e.g. ``"alba"``).
       The voice embedding is loaded instantly from a pre-computed ``.safetensors``
       file.
    2. **Clone voice** — pass ``ref_audio`` with a path to a WAV/MP3 clip.
       The voice state is computed from the audio file once at startup.

    Granular Controls:
        pocket_language: Language config (``"english"``, ``"german_24l"``,
            ``"spanish_24l"``, ``"french_24l"``, ``"italian_24l"``, ``"portuguese_24l"``).
        temp: Sampling temperature (default ``0.7``; ``0.45`` = crisp technical,
            ``0.85`` = dramatic & expressive).
        lsd_decode_steps: Flow-matching decode steps (``1..8``, default ``1``;
            ``2..4`` sharpens articulation and intonation contour).
        noise_clamp: Optional Gaussian latent noise clamp (e.g. ``2.5``) to prevent
            breathy tail artifacts on long narration runs.
        eos_threshold: End-of-sequence threshold (default ``-4.0``).
        frames_after_eos: Optional trailing silence frames after EOS (useful for
            language shadowing pauses).
        quantize: Enable dynamic INT8 quantization for faster CPU inference.
        dialogue_voice: Optional secondary preset voice name or audio path used
            automatically when a chunk is enclosed in quotation marks or tagged
            with ``[voice:name]``.
    """

    _SAMPLE_RATE = 24000

    def __init__(
        self,
        ref_audio: str | Path | None = None,
        voice: str = "",
        speed: float = 1.0,
        pocket_language: str = "english",
        temp: float = 0.7,
        lsd_decode_steps: int = 1,
        noise_clamp: float | None = None,
        eos_threshold: float = -4.0,
        frames_after_eos: int | None = None,
        quantize: bool = False,
        truncate_prompt: bool = False,
        dialogue_voice: str = "",
    ) -> None:
        try:
            from pocket_tts import TTSModel  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "pocket-tts is not installed. Please install it using "
                "'uv add \"epuboverlay[pocket]\"' (or 'pip install \"epuboverlay[pocket]\"') "
                "to use the PocketSynthesizer."
            ) from e

        if not voice and not ref_audio:
            raise ValueError(
                "Either 'voice' (preset name) or 'ref_audio' (file path) must be provided."
            )
        if voice and ref_audio:
            raise ValueError(
                "Provide either 'voice' (preset) or 'ref_audio' (clone), not both."
            )

        self._speed = float(speed)
        self.pocket_language = (pocket_language or "english").strip() or "english"
        self.temp = float(temp)
        self.lsd_decode_steps = max(1, int(lsd_decode_steps))
        self.noise_clamp = float(noise_clamp) if noise_clamp not in (None, "") else None
        self.eos_threshold = float(eos_threshold)
        self.frames_after_eos = (
            max(0, int(frames_after_eos)) if frames_after_eos not in (None, "") else None
        )
        self.quantize = bool(quantize)
        self.truncate_prompt = bool(truncate_prompt)
        self.dialogue_voice = (dialogue_voice or "").strip()
        self._lock = threading.Lock()
        self._state_cache: dict[str, object] = {}

        # Load model once, passing granular parameters when customized
        use_custom_load = (
            self.pocket_language != "english"
            or abs(self.temp - 0.7) > 1e-4
            or self.lsd_decode_steps != 1
            or self.noise_clamp is not None
            or abs(self.eos_threshold - (-4.0)) > 1e-4
            or self.quantize
        )
        if use_custom_load:
            try:
                self._model = TTSModel.load_model(
                    language=self.pocket_language,
                    temp=self.temp,
                    lsd_decode_steps=self.lsd_decode_steps,
                    noise_clamp=self.noise_clamp,
                    eos_threshold=self.eos_threshold,
                    quantize=self.quantize,
                )
            except TypeError:
                self._model = TTSModel.load_model()
        else:
            self._model = TTSModel.load_model()

        if voice:
            if voice not in POCKET_VOICES:
                raise ValueError(
                    f"Unknown PocketTTS preset voice: '{voice}'. "
                    f"Available: {', '.join(POCKET_VOICES)}"
                )
            self.voice = voice
            self._voice_state = self._get_or_load_state(voice)
            self._voice_label = voice
        else:
            self.voice = ""
            self.ref_audio = str(ref_audio)
            self._voice_state = self._get_or_load_state(self.ref_audio, truncate=self.truncate_prompt)
            self._voice_label = Path(ref_audio).name  # type: ignore[arg-type]

        # Pre-load optional dialogue voice state for zero-overhead character switching
        self._dialogue_state = None
        if self.dialogue_voice:
            try:
                self._dialogue_state = self._get_or_load_state(self.dialogue_voice)
            except Exception:
                self._dialogue_state = None

    def _get_or_load_state(self, prompt_key: str, truncate: bool = False) -> object:
        if prompt_key in self._state_cache:
            return self._state_cache[prompt_key]
        try:
            import torch
            ctx = torch.no_grad()
        except ImportError:
            from contextlib import nullcontext
            ctx = nullcontext()
        with ctx:
            try:
                state = self._model.get_state_for_audio_prompt(prompt_key, truncate=truncate)
            except TypeError:
                state = self._model.get_state_for_audio_prompt(prompt_key)
        self._state_cache[prompt_key] = state
        return state

    @property
    def sample_rate(self) -> int:
        return int(getattr(self._model, "sample_rate", self._SAMPLE_RATE) or self._SAMPLE_RATE)

    @property
    def speed(self) -> float:
        return self._speed

    def _resolve_state_and_text(self, text: str) -> tuple[object, str]:
        """Select voice state based on inline [voice:...] tags or quoted dialogue."""
        match = _INLINE_VOICE_RE.match(text)
        if match:
            requested = match.group(1).strip().lower()
            cleaned = text[match.end():].strip()
            if requested in POCKET_VOICES:
                try:
                    return self._get_or_load_state(requested), cleaned
                except Exception:
                    return self._voice_state, cleaned
            return self._voice_state, cleaned

        if self._dialogue_state is not None and _QUOTED_DIALOGUE_RE.match(text):
            return self._dialogue_state, text

        return self._voice_state, text

    def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", 0

        import numpy as np  # type: ignore[import-untyped]

        active_state, clean_text = self._resolve_state_and_text(text)
        if not clean_text.strip():
            return b"", 0

        # TTSModel.generate_audio is not thread-safe; guard with instance lock
        # Use torch.no_grad() instead of torch.inference_mode() because PocketTTS
        # spawns an internal worker thread for autoregressive streaming generation
        # which performs in-place KV cache updates outside the caller's thread-local InferenceMode.
        with self._lock:
            try:
                import torch
                ctx = torch.no_grad()
            except ImportError:
                from contextlib import nullcontext
                ctx = nullcontext()
            with ctx:
                if self.frames_after_eos is not None:
                    try:
                        audio = self._model.generate_audio(
                            active_state,
                            clean_text,
                            frames_after_eos=self.frames_after_eos,
                        )
                    except TypeError:
                        audio = self._model.generate_audio(active_state, clean_text)
                else:
                    audio = self._model.generate_audio(active_state, clean_text)

        # Convert to numpy if needed
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        elif hasattr(audio, "numpy"):
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

        # Convert float32 -> int16 PCM
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767.0).astype(np.int16)

        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return out_io.getvalue(), len(audio_int16)
