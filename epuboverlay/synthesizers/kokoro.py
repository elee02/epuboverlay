"""Kokoro-82M synthesizer with built-in voices and voice formula mixing."""
from __future__ import annotations

import io
import wave
from typing import Any

from epuboverlay.synthesizers.base import BaseSynthesizer


# Kokoro built-in voice identifiers.
KOKORO_VOICES: list[str] = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    "ef_dora", "em_alex", "em_santa",
    "ff_siwis",
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola",
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
]


def _parse_voice_formula(pipeline: Any, formula: str) -> Any:
    """Parse a voice formula string like ``"af_heart*0.6+af_sky*0.4"`` and
    return a blended voice tensor.

    Each term is ``voice_name*weight``, separated by ``+``.  Weights are
    normalised so they sum to 1.0.
    """
    import torch  # type: ignore[import-untyped]

    terms: list[tuple[str, float]] = []
    for segment in formula.split("+"):
        part = segment.strip()
        if not part:
            continue
        if "*" not in part:
            raise ValueError(
                f"Each component must be in the form voice*weight, got: '{part}'"
            )
        voice_name, raw_weight = part.split("*", 1)
        voice_name = voice_name.strip()
        if voice_name not in KOKORO_VOICES:
            raise ValueError(f"Unknown Kokoro voice: {voice_name}")
        weight = float(raw_weight.strip())
        if weight <= 0:
            raise ValueError(f"Weight for {voice_name} must be positive")
        terms.append((voice_name, weight))

    if not terms:
        raise ValueError("Voice formula produced no components")

    total_weight = sum(w for _, w in terms)
    weighted_sum: torch.Tensor | None = None
    for voice_name, weight in terms:
        normalised = weight / total_weight
        voice_tensor = pipeline.load_single_voice(voice_name)
        if weighted_sum is None:
            weighted_sum = normalised * voice_tensor
        else:
            weighted_sum = weighted_sum + normalised * voice_tensor

    assert weighted_sum is not None
    return weighted_sum.to("cpu")


import threading


class KokoroSynthesizer(BaseSynthesizer):
    """Kokoro-82M synthesizer — lightweight, fast, with built-in voices and
    voice formula blending support.

    Args:
        voice: Name of a built-in voice (e.g. ``"af_heart"``).
        voice_formula: Weighted voice blend string
            (e.g. ``"af_heart*0.6+af_sky*0.4"``).  Mutually exclusive
            with *voice*.
        speed: Speech speed factor (default 1.0).
        lang_code: Kokoro language code (default ``"a"`` for American English).
        device: Torch device (default ``"cpu"``).
    """

    _SAMPLE_RATE = 24000
    _lock = threading.Lock()

    def __init__(
        self,
        voice: str = "",
        voice_formula: str = "",
        speed: float = 1.0,
        lang_code: str = "a",
        device: str = "cpu",
    ) -> None:
        try:
            from kokoro import KPipeline  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "kokoro is not installed. Please install it using 'pip install kokoro>=0.9.4' "
                "to use the KokoroSynthesizer."
            ) from e

        if not voice and not voice_formula:
            raise ValueError("Either 'voice' or 'voice_formula' must be provided.")

        import inspect
        sig = inspect.signature(KPipeline.__init__)
        pipe_kwargs = {"lang_code": lang_code, "device": device}
        if "repo_id" in sig.parameters:
            pipe_kwargs["repo_id"] = "hexgrad/Kokoro-82M"
        self._pipeline = KPipeline(**pipe_kwargs)
        self._speed = speed
        self._lang_code = lang_code

        # Resolve the voice tensor once at startup
        if voice_formula:
            self._voice = _parse_voice_formula(self._pipeline, voice_formula)
            self._voice_label = voice_formula
        else:
            if voice not in KOKORO_VOICES:
                raise ValueError(
                    f"Unknown Kokoro voice: '{voice}'. "
                    f"Available voices: {', '.join(KOKORO_VOICES)}"
                )
            self._voice = voice
            self._voice_label = voice

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

        audio_parts: list[np.ndarray] = []
        with self._lock:
            segments = list(self._pipeline(text, voice=self._voice, speed=self._speed))

        for segment in segments:
            audio = segment.audio
            if hasattr(audio, "numpy"):
                audio = audio.numpy()
            audio_parts.append(np.asarray(audio, dtype="float32"))

        if not audio_parts:
            return b"", 0

        combined = np.concatenate(audio_parts).astype("float32", copy=False)

        # Convert float32 → int16 PCM
        audio_clipped = np.clip(combined, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767.0).astype(np.int16)

        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

        return out_io.getvalue(), len(audio_int16)
