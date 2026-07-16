"""Synthesizers package for epuboverlay.

Exposes a registry-based factory for creating TTS engine backends.
"""
from __future__ import annotations

from typing import Any, Callable

from epuboverlay.synthesizers.base import BaseSynthesizer, FrameTimedSynthesizer
from epuboverlay.synthesizers.dummy import DummySynthesizer
from epuboverlay.synthesizers.f5tts import F5TTSSynthesizer
from epuboverlay.synthesizers.kokoro import KokoroSynthesizer, KOKORO_VOICES
from epuboverlay.synthesizers.pocket import PocketSynthesizer, POCKET_VOICES

# Registry mapping backend ID string -> factory callable
_REGISTRY: dict[str, Callable[..., BaseSynthesizer]] = {
    "dummy": lambda **kw: DummySynthesizer(
        sample_rate=int(kw.get("frame_rate", 24000) or kw.get("sample_rate", 24000)),
        chars_per_sec=float(kw.get("chars_per_sec", 15.0)),
    ),
    "f5-tts": lambda **kw: F5TTSSynthesizer(
        ref_audio=kw["ref_audio_path"] if "ref_audio_path" in kw else kw["ref_audio"],
        ref_text=kw["ref_text"],
        model_name=kw.get("model_name", "F5TTS_Base"),
        device=kw.get("device"),
        speed=float(kw.get("speed", 1.0)),
        nfe_step=int(kw.get("nfe_step", 32)),
        compile=bool(kw.get("compile", False)),
    ),
    "kokoro": lambda **kw: KokoroSynthesizer(
        voice=kw.get("voice", ""),
        voice_formula=kw.get("voice_formula", ""),
        speed=float(kw.get("speed", 1.0)),
        lang_code=kw.get("lang_code", "a"),
        device=kw.get("device", "cpu"),
    ),
    "pocket-tts": lambda **kw: PocketSynthesizer(
        ref_audio=kw.get("ref_audio_path") or kw.get("ref_audio") or None,
        voice=kw.get("pocket_voice", "") or kw.get("voice", ""),
        speed=float(kw.get("speed", 1.0)),
    ),
}


def create_synthesizer(synth_id: str, **kwargs: Any) -> BaseSynthesizer:
    """Create and return a synthesizer instance for the given identifier.

    Args:
        synth_id: One of 'dummy', 'f5-tts', 'kokoro', 'pocket-tts'.
        **kwargs: Synthesizer-specific configuration options.
    """
    if synth_id not in _REGISTRY:
        raise ValueError(
            f"Unknown synthesizer: '{synth_id}'. "
            f"Available options: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[synth_id](**kwargs)


__all__ = [
    "BaseSynthesizer",
    "FrameTimedSynthesizer",
    "DummySynthesizer",
    "F5TTSSynthesizer",
    "KokoroSynthesizer",
    "PocketSynthesizer",
    "KOKORO_VOICES",
    "POCKET_VOICES",
    "create_synthesizer",
]
