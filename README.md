# epuboverlay

Minimal EPUB → F5-TTS orchestration helpers with internal timestamp capture (Approach B).

## What is implemented

- EPUB spine text extraction (`extract_spine_text_chunks`)
- Internal frame-count based timestamp accumulation (`synthesize_with_internal_timestamps`)
- `.lrc` formatting (`format_lrc`)

This enables a pipeline where your F5-TTS wrapper returns `(audio_bytes, generated_frame_count)` per chunk, and the tool builds synchronized `.lrc` lines directly from those internal generation durations.

## Testing

```bash
python -m unittest discover -v
```
