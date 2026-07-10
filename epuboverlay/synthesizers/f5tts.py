"""F5-TTS synthesizer with pre-computed reference audio caching."""
from __future__ import annotations

import io
import wave
from pathlib import Path

from epuboverlay.synthesizers.base import BaseSynthesizer


class F5TTSSynthesizer(BaseSynthesizer):
    """A synthesizer that uses F5-TTS for generation with cached reference audio/text representations."""

    def __init__(
        self,
        ref_audio: str | Path,
        ref_text: str,
        model_name: str = "F5TTS_Base",
        device: str | None = None,
        speed: float = 1.0,
        nfe_step: int = 32,
        compile: bool = False,
    ) -> None:
        try:
            from f5_tts.api import F5TTS, preprocess_ref_audio_text
            import torch
            import torchaudio
            from f5_tts.infer.utils_infer import convert_char_to_pinyin
        except ImportError as e:
            raise ImportError(
                "f5-tts is not installed. Please install it using 'pip install f5-tts' "
                "to use the F5TTSSynthesizer."
            ) from e

        self.f5 = F5TTS(model=model_name, device=device)
        self.ref_audio = str(ref_audio)
        self.ref_text = ref_text
        self._speed = speed
        self.nfe_step = nfe_step
        self.device = self.f5.device

        # Preprocess the reference audio and text once
        ref_file_proc, ref_text_proc = preprocess_ref_audio_text(self.ref_audio, self.ref_text, show_info=print)
        self.ref_text = ref_text_proc

        # Load reference audio waveform
        ref_wav, ref_sr = torchaudio.load(ref_file_proc)
        if ref_wav.shape[0] > 1:
            ref_wav = torch.mean(ref_wav, dim=0, keepdim=True)

        # Normalize RMS
        self.target_rms = 0.1
        self.rms = torch.sqrt(torch.mean(torch.square(ref_wav))).item()
        if self.rms < self.target_rms:
            ref_wav = ref_wav * self.target_rms / self.rms

        # Resample to the target sample rate (24000 Hz)
        self.target_sample_rate = self.f5.target_sample_rate
        if ref_sr != self.target_sample_rate:
            resampler = torchaudio.transforms.Resample(ref_sr, self.target_sample_rate)
            ref_wav = resampler(ref_wav)

        # Move reference waveform to device
        ref_wav = ref_wav.to(self.device)

        # Pre-compute Mel-spectrogram
        with torch.inference_mode():
            # mel_spec expects 2D [channels, samples], returns 3D [1, channels, seq_len]
            ref_mel = self.f5.ema_model.mel_spec(ref_wav)
            # Permute to [1, seq_len, channels]
            self.ref_mel = ref_mel.permute(0, 2, 1)

        # Save precomputed lengths and other settings
        self.hop_length = self.f5.ema_model.mel_spec.hop_length
        self.ref_audio_len = ref_wav.shape[-1] // self.hop_length
        self.ref_pinyins = convert_char_to_pinyin([self.ref_text])[0]

        if compile:
            try:
                print("Compiling model (torch.compile) to optimize inference speed. The first chunk will take 1-2 minutes...")
                self.f5.ema_model = torch.compile(self.f5.ema_model)
            except Exception as e:
                print(f"Warning: torch.compile failed ({e}). Falling back to uncompiled model.")

    @property
    def sample_rate(self) -> int:
        return self.target_sample_rate

    @property
    def speed(self) -> float:
        return self._speed

    def synthesize(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", 0

        import numpy as np
        import torch
        from f5_tts.infer.utils_infer import convert_char_to_pinyin

        # Pre-tokenize the input chunk
        gen_pinyins = convert_char_to_pinyin([text])[0]
        final_text_list = [self.ref_pinyins + gen_pinyins]

        # Calculate duration
        ref_text_len = len(self.ref_text.encode("utf-8"))
        gen_text_len = len(text.encode("utf-8"))

        # Apply the default short-text speed scaling factor
        local_speed = self._speed
        if gen_text_len < 10:
            local_speed = 0.3

        duration = self.ref_audio_len + int(self.ref_audio_len / ref_text_len * gen_text_len / local_speed)

        # Inference
        with torch.inference_mode():
            generated, _ = self.f5.ema_model.sample(
                cond=self.ref_mel,
                text=final_text_list,
                duration=duration,
                steps=self.nfe_step,
                cfg_strength=2.0,  # default cfg strength
                sway_sampling_coef=-1,  # default sway sampling
            )

            generated = generated.to(torch.float32)
            generated = generated[:, self.ref_audio_len:, :]
            generated = generated.permute(0, 2, 1)

            if self.f5.mel_spec_type == "vocos":
                generated_wave = self.f5.vocoder.decode(generated)
            elif self.f5.mel_spec_type == "bigvgan":
                generated_wave = self.f5.vocoder(generated)

            if self.rms < self.target_rms:
                generated_wave = generated_wave * self.rms / self.target_rms

            wav = generated_wave.squeeze().cpu().numpy()

        # Normalize/convert float32 numpy array to 16-bit PCM WAV
        if wav.dtype != np.int16:
            audio_clipped = np.clip(wav, -1.0, 1.0)
            audio_int16 = (audio_clipped * 32767.0).astype(np.int16)
        else:
            audio_int16 = wav

        out_io = io.BytesIO()
        with wave.open(out_io, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(self.target_sample_rate)
            wav_out.writeframes(audio_int16.tobytes())

        return out_io.getvalue(), len(audio_int16)
