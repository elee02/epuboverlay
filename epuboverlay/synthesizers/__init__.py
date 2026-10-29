"""Synthesizers package for epuboverlay.

Exposes a registry-based factory for creating TTS engine backends.
"""
from __future__ import annotations

from typing import Any, Callable

from epuboverlay.synthesizers.base import BaseSynthesizer, FrameTimedSynthesizer
from epuboverlay.synthesizers.dummy import DummySynthesizer
from epuboverlay.synthesizers.f5tts import F5TTSSynthesizer
from epuboverlay.synthesizers.fish import (
    FISH_EMOTION_TAGS,
    FISH_LANGUAGES,
    FishSpeechSynthesizer,
)
from epuboverlay.synthesizers.kokoro import KOKORO_VOICES, KokoroSynthesizer
from epuboverlay.synthesizers.pocket import (
    POCKET_LANGUAGES,
    POCKET_VOICES,
    PocketSynthesizer,
)
from epuboverlay.synthesizers.qwen3 import (
    QWEN3_LANGUAGES,
    QWEN3_MODELS,
    QWEN3_VOICES,
    Qwen3TTSSynthesizer,
    clear_qwen_model_cache,
)

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
        pocket_language=kw.get("pocket_language", "english") or "english",
        temp=float(kw.get("temp", 0.7) if kw.get("temp") not in (None, "") else 0.7),
        lsd_decode_steps=int(kw.get("lsd_decode_steps", 1) if kw.get("lsd_decode_steps") not in (None, "") else 1),
        noise_clamp=float(kw["noise_clamp"]) if kw.get("noise_clamp") not in (None, "") else None,
        eos_threshold=float(kw.get("eos_threshold", -4.0) if kw.get("eos_threshold") not in (None, "") else -4.0),
        frames_after_eos=int(kw["frames_after_eos"]) if kw.get("frames_after_eos") not in (None, "") else None,
        quantize=bool(kw.get("quantize", False)),
        truncate_prompt=bool(kw.get("truncate_prompt", False)),
        dialogue_voice=kw.get("dialogue_voice", "") or "",
    ),
    "qwen3-tts": lambda **kw: Qwen3TTSSynthesizer(
        model_name=kw.get("qwen_model") or kw.get("model_name") or "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        mode=kw.get("qwen_mode") or kw.get("mode") or "custom_voice",
        speaker=kw.get("qwen_speaker") or kw.get("speaker") or kw.get("voice") or "Ryan",
        instruct=kw.get("instruct", "") or "",
        language=kw.get("language") or kw.get("lang_code") or "auto",
        ref_audio=kw.get("ref_audio_path") or kw.get("ref_audio") or None,
        ref_text=kw.get("ref_text", "") or "",
        speed=float(kw.get("speed", 1.0)),
        temp=float(kw.get("temp", 0.7) if kw.get("temp") not in (None, "") else 0.7),
        device=kw.get("device"),
    ),
    "fish-speech": lambda **kw: FishSpeechSynthesizer(
        ref_audio=kw.get("ref_audio_path") or kw.get("ref_audio") or None,
        ref_text=kw.get("ref_text", "") or "",
        emotion_tag=kw.get("emotion_tag", "") or "",
        language=kw.get("language") or kw.get("lang_code") or "auto",
        temp=float(kw.get("temp", 0.7) if kw.get("temp") not in (None, "") else 0.7),
        top_p=float(kw.get("top_p", 0.7) if kw.get("top_p") not in (None, "") else 0.7),
        repetition_penalty=float(kw.get("repetition_penalty", 1.2) if kw.get("repetition_penalty") not in (None, "") else 1.2),
        speed=float(kw.get("speed", 1.0)),
        api_url=kw.get("fish_api_url") or kw.get("api_url") or "",
        api_key=kw.get("fish_api_key") or kw.get("api_key") or "",
        device=kw.get("device"),
    ),
}

AVAILABLE_SYNTHESIZERS: list[str] = list(_REGISTRY.keys())


def create_synthesizer(synth_id: str, **kwargs: Any) -> BaseSynthesizer:
    """Create and return a synthesizer instance for the given identifier.

    Args:
        synth_id: One of 'dummy', 'f5-tts', 'kokoro', 'pocket-tts',
            'qwen3-tts', 'fish-speech'.
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
    "Qwen3TTSSynthesizer",
    "FishSpeechSynthesizer",
    "KOKORO_VOICES",
    "POCKET_VOICES",
    "POCKET_LANGUAGES",
    "QWEN3_MODELS",
    "QWEN3_VOICES",
    "QWEN3_LANGUAGES",
    "FISH_LANGUAGES",
    "FISH_EMOTION_TAGS",
    "AVAILABLE_SYNTHESIZERS",
    "create_synthesizer",
]
