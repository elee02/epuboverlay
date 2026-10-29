"""FastAPI web server for epuboverlay dashboard."""
from __future__ import annotations

import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import argparse
import asyncio
import json
import psutil
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import zipfile
from pathlib import Path
from queue import Empty

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

# Synthesizer imports moved to jobs.py runner process
from epuboverlay.web.jobs import JobManager, Job, JobStatus

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="epuboverlay Dashboard", version="0.1.0")
job_manager = JobManager()

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MiB


@app.middleware("http")
async def verify_same_origin(request: Request, call_next):
    """Block cross-origin CSRF requests to mutating /api/* endpoints and prevent stale static caching."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin:
            parsed_origin = urlparse(origin)
            origin_host = (parsed_origin.hostname or "").lower()
            host_header = (request.headers.get("host") or "").split(":")[0].lower()
            allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
            if host_header:
                allowed_hosts.add(host_header)
            if origin_host not in allowed_hosts:
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Cross-origin request blocked from origin: {origin}"},
                )
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


async def _read_upload_bytes(upload: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read an UploadFile in chunks while enforcing a maximum byte limit."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded file exceeds maximum allowed size ({max_bytes // (1024 * 1024)} MiB).",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _save_upload_to_temp(
    upload: UploadFile,
    suffix: str = ".tmp",
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> Path:
    """Stream an UploadFile to a temporary file while enforcing a maximum byte limit."""
    safe_suffix = re.sub(r"[^.A-Za-z0-9_-]", "", suffix) or ".tmp"
    if not safe_suffix.startswith("."):
        safe_suffix = "." + safe_suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=safe_suffix)
    tmp_path = Path(tmp.name)
    total = 0
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded file exceeds maximum allowed size ({max_bytes // (1024 * 1024)} MiB).",
                )
            tmp.write(chunk)
        tmp.close()
        return tmp_path
    except Exception:
        try:
            tmp.close()
        except Exception:
            pass
        tmp_path.unlink(missing_ok=True)
        raise


def get_installed_synthesizers() -> dict[str, bool]:
    """Detect which TTS synthesizers are installed in the current environment."""
    import importlib.util

    return {
        "dummy": True,
        "kokoro": importlib.util.find_spec("kokoro") is not None,
        "pocket-tts": importlib.util.find_spec("pocket_tts") is not None,
        "qwen3-tts": importlib.util.find_spec("qwen_tts") is not None,
        "f5-tts": importlib.util.find_spec("f5_tts") is not None,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard SPA."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


def get_system_stats():
    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)

    # RAM
    ram = psutil.virtual_memory()
    ram_used = ram.used / (1024 ** 3)
    ram_total = ram.total / (1024 ** 3)
    ram_percent = ram.percent

    # Disk
    disk = psutil.disk_usage(str(Path.home()))
    disk_used = disk.used / (1024 ** 3)
    disk_total = disk.total / (1024 ** 3)
    disk_percent = disk.percent

    # GPU
    gpu_data = None
    try:
        cmd = ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        parts = res.stdout.strip().split(",")
        if len(parts) >= 5:
            vram_used = float(parts[1].strip()) / 1024.0
            vram_total = float(parts[2].strip()) / 1024.0
            gpu_data = {
                "name": parts[0].strip(),
                "vram_used": round(vram_used, 2),
                "vram_total": round(vram_total, 2),
                "utilization": float(parts[3].strip()),
                "temperature": float(parts[4].strip())
            }
    except Exception:
        pass

    return {
        "cpu_percent": cpu_percent,
        "ram_used_gb": round(ram_used, 2),
        "ram_total_gb": round(ram_total, 2),
        "ram_percent": ram_percent,
        "disk_used_gb": round(disk_used, 2),
        "disk_total_gb": round(disk_total, 2),
        "disk_percent": disk_percent,
        "gpu": gpu_data
    }


@app.get("/api/stats")
async def get_stats():
    """Return live system resource stats."""
    return get_system_stats()


SETTINGS_FILE = Path.home() / ".epuboverlay" / "settings.json"
REFERENCES_DIR = Path.home() / ".epuboverlay" / "references"
REFERENCES_METADATA_FILE = REFERENCES_DIR / "metadata.json"

DEFAULT_SETTINGS = {
    "synthesizer": "f5-tts",
    "speed": 1.0,
    "max_chars": 150,
    "frame_rate": 24000.0,
    "concurrency": 2,
    "nfe_step": 32,
    "compile": False,
    "voice": "af_heart",
    "voice_formula": "",
    "lang_code": "a",
    "device": "",
    "expand_numerals": True,
    "resolve_contractions": True,
    "resolve_heteronyms": True,
    "harmonize_punctuation": True,
    "custom_lexicon": []
}

def load_settings_data() -> dict:
    if not SETTINGS_FILE.exists():
        return {"current_settings": DEFAULT_SETTINGS.copy()}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "current_settings" not in data:
                data["current_settings"] = DEFAULT_SETTINGS.copy()
            else:
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data["current_settings"]:
                        data["current_settings"][k] = v
            # Clean out profile keys
            if "profiles" in data:
                del data["profiles"]
            return data
    except Exception:
        return {"current_settings": DEFAULT_SETTINGS.copy()}

def save_settings_data(data: dict) -> None:
    # Filter profiles if somehow present
    if "profiles" in data:
        del data["profiles"]
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_references() -> list[dict]:
    if not REFERENCES_METADATA_FILE.exists():
        return []
    try:
        with open(REFERENCES_METADATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_references(refs: list[dict]) -> None:
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    with open(REFERENCES_METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(refs, f, indent=2, ensure_ascii=False)

# Playground cache in RAM
_PLAYGROUND_HISTORY: list[dict] = []



@app.get("/api/config")
async def get_config():
    """Return available synthesizers, voices, languages, scenarios, and defaults."""
    from epuboverlay.normalization import NARRATION_SCENARIOS
    from epuboverlay.synthesizers import (
        KOKORO_VOICES,
        POCKET_LANGUAGES,
        POCKET_VOICES,
        QWEN3_LANGUAGES,
        QWEN3_MODELS,
        QWEN3_VOICES,
    )
    data = load_settings_data()
    current = data.get("current_settings", {})
    installed = get_installed_synthesizers()

    # Pick default synthesizer based on what is actually installed
    saved_synth = current.get("synthesizer")
    if saved_synth and installed.get(saved_synth, False):
        default_synth = saved_synth
    elif installed.get("pocket-tts", False):
        default_synth = "pocket-tts"
    elif installed.get("kokoro", False):
        default_synth = "kokoro"
    elif installed.get("qwen3-tts", False):
        default_synth = "qwen3-tts"
    elif installed.get("f5-tts", False):
        default_synth = "f5-tts"
    else:
        default_synth = "dummy"

    defaults = {
        "synthesizer": default_synth,
        "scenario": current.get("scenario", "custom"),
        "speed": current.get("speed", 1.0),
        "max_chars": current.get("max_chars", 150),
        "frame_rate": current.get("frame_rate", 24000.0),
        "concurrency": current.get("concurrency", 2),
        "nfe_step": current.get("nfe_step", 32),
        "compile": current.get("compile", False),
        "voice": current.get("voice", "af_heart"),
        "voice_formula": current.get("voice_formula", ""),
        "lang_code": current.get("lang_code", "a"),
        "language": current.get("language", "auto"),
        "device": current.get("device", ""),
        "pocket_voice": current.get("pocket_voice", "alba"),
        "pocket_language": current.get("pocket_language", "english"),
        "temp": current.get("temp", 0.7),
        "lsd_decode_steps": current.get("lsd_decode_steps", 1),
        "noise_clamp": current.get("noise_clamp", ""),
        "eos_threshold": current.get("eos_threshold", -4.0),
        "frames_after_eos": current.get("frames_after_eos", ""),
        "quantize": current.get("quantize", False),
        "dialogue_voice": current.get("dialogue_voice", ""),
        "qwen_model": current.get("qwen_model", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        "qwen_mode": current.get("qwen_mode", "custom_voice"),
        "qwen_speaker": "Ryan" if current.get("qwen_speaker") in (None, "", "Chelsie") else current.get("qwen_speaker", "Ryan"),
        "instruct": current.get("instruct", ""),
    }

    return {
        "synthesizers": [
            "pocket-tts",
            "kokoro",
            "qwen3-tts",
            "f5-tts",
            "dummy",
        ],
        "installed_synthesizers": installed,
        "kokoro_voices": KOKORO_VOICES,
        "pocket_voices": POCKET_VOICES,
        "pocket_languages": POCKET_LANGUAGES,
        "qwen3_models": QWEN3_MODELS,
        "qwen3_voices": QWEN3_VOICES,
        "qwen3_languages": QWEN3_LANGUAGES,
        "scenarios": NARRATION_SCENARIOS,
        "defaults": defaults,
    }


@app.get("/api/settings")
async def get_settings():
    """Get the current settings."""
    return load_settings_data()


from fastapi import Body

@app.post("/api/settings")
async def save_settings(settings: dict = Body(...)):
    """Save current settings."""
    data = load_settings_data()
    data["current_settings"] = settings
    save_settings_data(data)
    return {"status": "saved", "settings": data["current_settings"]}


VOICE_BLENDS_FILE = Path.home() / ".epuboverlay" / "voice_blends.json"

def load_voice_blends() -> list[dict]:
    if not VOICE_BLENDS_FILE.exists():
        return []
    try:
        with open(VOICE_BLENDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_voice_blends(blends: list[dict]) -> None:
    VOICE_BLENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(VOICE_BLENDS_FILE, "w", encoding="utf-8") as f:
        json.dump(blends, f, indent=2, ensure_ascii=False)

@app.get("/api/voice-blends")
async def get_voice_blends():
    """List saved voice blends."""
    return load_voice_blends()

@app.post("/api/voice-blends")
async def create_voice_blend(blend: dict = Body(...)):
    """Save a new voice blend."""
    blends = load_voice_blends()
    name = blend.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Blend name is required")
    # Remove existing blend with the same name if any
    blends = [b for b in blends if b.get("name", "").strip().lower() != name.lower()]
    blends.append(blend)
    save_voice_blends(blends)
    return {"status": "saved", "blends": blends}

@app.delete("/api/voice-blends/{name}")
async def delete_voice_blend(name: str):
    """Delete a voice blend by name."""
    blends = load_voice_blends()
    filtered = [b for b in blends if b.get("name", "").strip().lower() != name.strip().lower()]
    if len(filtered) == len(blends):
        raise HTTPException(status_code=404, detail="Voice blend not found")
    save_voice_blends(filtered)
    return {"status": "deleted", "blends": filtered}




@app.get("/api/references")
async def get_references():
    """List all saved reference audio-text pairs."""
    return load_references()


@app.post("/api/references")
async def create_reference(
    name: str = Form(...),
    text: str = Form(""),
    audio: UploadFile = File(...),
):
    """Save a new reference audio-text pair."""
    import time
    ref_id = f"ref_{int(time.time() * 1000)}"
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    
    suffix = re.sub(r"[^.A-Za-z0-9]", "", Path(audio.filename or "audio.wav").suffix) or ".wav"
    audio_filename = f"{ref_id}{suffix}"
    audio_path = REFERENCES_DIR / audio_filename
    
    audio_bytes = await _read_upload_bytes(audio)
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)
        
    refs = load_references()
    new_ref = {
        "id": ref_id,
        "name": name,
        "text": text,
        "audio_filename": audio_filename,
    }
    refs.append(new_ref)
    save_references(refs)
    return new_ref


@app.get("/api/references/{ref_id}/audio")
async def get_reference_audio(ref_id: str):
    """Retrieve the audio file for a reference voice."""
    refs = load_references()
    ref = next((r for r in refs if r["id"] == ref_id), None)
    if not ref:
        raise HTTPException(status_code=404, detail="Reference voice not found")
    
    audio_path = REFERENCES_DIR / ref["audio_filename"]
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Reference audio file not found")
        
    ext = audio_path.suffix.lower()
    media_type = "audio/wav"
    if ext == ".mp3":
        media_type = "audio/mpeg"
    elif ext == ".ogg":
        media_type = "audio/ogg"
    elif ext in (".m4a", ".mp4"):
        media_type = "audio/mp4"
        
    return FileResponse(path=str(audio_path), media_type=media_type)


@app.put("/api/references/{ref_id}")
async def update_reference(
    ref_id: str,
    name: str = Form(...),
    text: str = Form(""),
):
    """Update name or transcript text of a saved reference voice."""
    refs = load_references()
    for ref in refs:
        if ref["id"] == ref_id:
            ref["name"] = name
            ref["text"] = text
            save_references(refs)
            return ref
    raise HTTPException(status_code=404, detail="Reference voice not found")


@app.delete("/api/references/{ref_id}")
async def delete_reference(ref_id: str):
    """Delete a saved reference voice and its audio file."""
    refs = load_references()
    ref_to_delete = None
    for ref in refs:
        if ref["id"] == ref_id:
            ref_to_delete = ref
            break
            
    if not ref_to_delete:
        raise HTTPException(status_code=404, detail="Reference voice not found")
        
    audio_path = REFERENCES_DIR / ref_to_delete["audio_filename"]
    try:
        audio_path.unlink(missing_ok=True)
    except Exception:
        pass
        
    refs = [r for r in refs if r["id"] != ref_id]
    save_references(refs)
    return {"status": "deleted"}


@app.get("/api/playground/history")
async def get_playground_history():
    """Get metadata for recently synthesized audios in the playground."""
    return [
        {
            "id": item["id"],
            "timestamp": item["timestamp"],
            "synthesizer": item["synthesizer"],
            "text": item["text"],
            "settings": item["settings"],
        }
        for item in _PLAYGROUND_HISTORY
    ]


@app.get("/api/playground/audio/{audio_id}")
async def get_playground_audio(audio_id: str):
    """Retrieve the audio bytes of a synthesized item in playground history."""
    item = next((x for x in _PLAYGROUND_HISTORY if x["id"] == audio_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Audio item not found in playground RAM history.")
    from fastapi import Response
    return Response(content=item["audio_bytes"], media_type="audio/wav")


@app.delete("/api/playground/cache")
async def clear_playground_cache():
    """Clear all playground history items from RAM cache."""
    _PLAYGROUND_HISTORY.clear()
    import gc
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    gc.collect()
    return {"status": "cleared"}




@app.get("/api/jobs")
async def list_jobs():
    """List all jobs."""
    return [job.to_dict() for job in job_manager.list_jobs()]


_PKG_ALIASES = {
    "f5-tts": "f5",
    "pocket-tts": "pocket",
    "qwen3-tts": "qwen",
    "kokoro": "kokoro",
}


@app.post("/api/jobs")
async def create_job(
    epub: UploadFile = File(...),
    synthesizer: str = Form("f5-tts"),
    scenario: str = Form("custom"),
    ref_audio: UploadFile | None = File(None),
    ref_text: str = Form(""),
    ref_id: str = Form(""),
    device: str = Form(""),
    speed: float = Form(1.0),
    max_chars: int = Form(150),
    frame_rate: float = Form(24000.0),
    concurrency: int = Form(2),
    nfe_step: int = Form(32),
    compile: bool = Form(False),
    voice: str = Form(""),
    voice_formula: str = Form(""),
    lang_code: str = Form("a"),
    language: str = Form("auto"),
    pocket_voice: str = Form(""),        # PocketTTS preset voice name
    pocket_language: str = Form("english"),
    temp: float = Form(0.7),
    lsd_decode_steps: int = Form(1),
    noise_clamp: str = Form(""),
    eos_threshold: float = Form(-4.0),
    frames_after_eos: str = Form(""),
    quantize: bool = Form(False),
    dialogue_voice: str = Form(""),
    qwen_model: str = Form("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
    qwen_mode: str = Form("custom_voice"),
    qwen_speaker: str = Form("Ryan"),
    instruct: str = Form(""),
    selected_chapters: str = Form(""),  # JSON array of idref strings
):
    """Submit a new EPUB overlay generation job."""
    if job_manager.has_running_job():
        raise HTTPException(
            status_code=409,
            detail="A job is already running. Please wait for it to complete or cancel it.",
        )

    # Validate synthesizer availability
    installed = get_installed_synthesizers()
    if not installed.get(synthesizer, False):
        pkg_alias = _PKG_ALIASES.get(synthesizer, synthesizer)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Synthesizer '{synthesizer}' is not installed in this environment. "
                f"To install it, run: uv sync --extra {pkg_alias} "
                f"(or pip install 'epuboverlay[{pkg_alias}]')"
            ),
        )

    # Validate based on selected synthesizer
    if synthesizer == "f5-tts":
        if not ref_id.strip() and (not ref_audio or not ref_text):
            raise HTTPException(
                status_code=400,
                detail="ref_audio and ref_text (or saved ref_id) are required for f5-tts synthesizer.",
            )
    elif synthesizer == "pocket-tts":
        if not ref_id.strip() and not ref_audio and not pocket_voice:
            raise HTTPException(
                status_code=400,
                detail="Either ref_audio (or saved ref_id) or pocket_voice (preset mode) is required for pocket-tts synthesizer.",
            )
    elif synthesizer == "kokoro":
        if not voice and not voice_formula:
            raise HTTPException(
                status_code=400,
                detail="Either voice or voice_formula is required for kokoro synthesizer.",
            )
    elif synthesizer == "qwen3-tts":
        if qwen_mode == "clone" and not ref_id.strip() and not ref_audio:
            raise HTTPException(
                status_code=400,
                detail="Reference audio (or saved ref_id) is required for Qwen3-TTS clone mode.",
            )

    parsed_chapters = None
    if selected_chapters:
        try:
            parsed_chapters = json.loads(selected_chapters)
            if not isinstance(parsed_chapters, list):
                raise ValueError()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="selected_chapters must be a valid JSON list of strings.",
            )

    # Save uploaded document (EPUB, PDF, DOCX, MD, TXT) to temp file preserving extension
    upload_suffix = Path(epub.filename or "book.epub").suffix or ".epub"
    tmp_epub_path = await _save_upload_to_temp(epub, suffix=upload_suffix)
    tmp_ref_audio_path: Path | None = None

    try:
        norm_settings = load_settings_data().get("current_settings", {})
        clone_capable = ("f5-tts", "pocket-tts", "qwen3-tts")

        # Save ref audio if provided
        ref_audio_path = None
        resolved_ref_text = ref_text
        if ref_id.strip() and synthesizer in clone_capable:
            refs = load_references()
            ref = next((r for r in refs if r["id"] == ref_id), None)
            if not ref:
                raise HTTPException(status_code=404, detail="Selected reference voice not found")
            audio_file = REFERENCES_DIR / ref["audio_filename"]
            if not audio_file.exists():
                raise HTTPException(status_code=404, detail="Selected reference audio file not found")
            ref_audio_path = audio_file
            if not ref_text.strip() and ref.get("text"):
                resolved_ref_text = ref["text"]
        elif ref_audio and ref_audio.filename and synthesizer in clone_capable:
            ref_suffix = Path(ref_audio.filename or "ref.wav").suffix or ".wav"
            tmp_ref_audio_path = await _save_upload_to_temp(ref_audio, suffix=ref_suffix)
            ref_audio_path = tmp_ref_audio_path

        config = {
            "synthesizer": synthesizer,
            "scenario": scenario or "custom",
            "ref_text": resolved_ref_text,
            "device": device or None,
            "speed": speed,
            "max_chars": max_chars,
            "frame_rate": frame_rate,
            "concurrency": concurrency,
            "nfe_step": nfe_step,
            "compile": compile,
            "voice": voice,
            "voice_formula": voice_formula,
            "lang_code": lang_code,
            "language": language or "auto",
            "pocket_voice": pocket_voice,
            "pocket_language": pocket_language or "english",
            "temp": temp,
            "lsd_decode_steps": lsd_decode_steps,
            "noise_clamp": float(noise_clamp) if noise_clamp.strip() else None,
            "eos_threshold": eos_threshold,
            "frames_after_eos": int(frames_after_eos) if frames_after_eos.strip() else None,
            "quantize": quantize,
            "dialogue_voice": dialogue_voice,
            "qwen_model": qwen_model,
            "qwen_mode": qwen_mode,
            "qwen_speaker": qwen_speaker,
            "instruct": instruct,
            "selected_chapters": parsed_chapters,
            "expand_numerals": norm_settings.get("expand_numerals", True),
            "resolve_contractions": norm_settings.get("resolve_contractions", True),
            "resolve_heteronyms": norm_settings.get("resolve_heteronyms", True),
            "harmonize_punctuation": norm_settings.get("harmonize_punctuation", True),
            "custom_lexicon": norm_settings.get("custom_lexicon", []),
        }
        if ref_audio_path:
            config["ref_audio_path"] = str(ref_audio_path)

        try:
            job = job_manager.create_job(
                input_epub_path=tmp_epub_path,
                original_filename=epub.filename or "output.epub",
                config=config,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
    finally:
        tmp_epub_path.unlink(missing_ok=True)
        if tmp_ref_audio_path is not None:
            tmp_ref_audio_path.unlink(missing_ok=True)

    job_manager.start_job(job.id)

    return job.to_dict()


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job details."""
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    if not job_manager.cancel_job(job_id):
        raise HTTPException(status_code=400, detail="Job is not running or not found.")
    return {"status": "cancellation_requested"}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    synthesizer: str | None = Form(None),
    scenario: str | None = Form(None),
    device: str | None = Form(None),
    speed: float | None = Form(None),
    max_chars: int | None = Form(None),
    frame_rate: float | None = Form(None),
    concurrency: int | None = Form(None),
    nfe_step: int | None = Form(None),
    compile: bool | None = Form(None),
    voice: str | None = Form(None),
    voice_formula: str | None = Form(None),
    lang_code: str | None = Form(None),
    language: str | None = Form(None),
    pocket_voice: str | None = Form(None),
    pocket_language: str | None = Form(None),
    temp: float | None = Form(None),
    lsd_decode_steps: int | None = Form(None),
    noise_clamp: str | None = Form(None),
    eos_threshold: float | None = Form(None),
    frames_after_eos: str | None = Form(None),
    quantize: bool | None = Form(None),
    dialogue_voice: str | None = Form(None),
    qwen_model: str | None = Form(None),
    qwen_mode: str | None = Form(None),
    qwen_speaker: str | None = Form(None),
    instruct: str | None = Form(None),
    ref_id: str | None = Form(None),
    ref_text: str | None = Form(None),
    ref_audio: UploadFile | None = File(None),
    selected_chapters: str | None = Form(None),
):
    """Resume a failed or cancelled job, optionally updating its configuration options."""
    if job_manager.has_running_job():
        raise HTTPException(
            status_code=409,
            detail="A job is already running. Please wait or cancel it first.",
        )

    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Only failed or cancelled jobs can be resumed. Current status: {job.status}",
        )

    target_synth = synthesizer if synthesizer is not None else job.config.get("synthesizer", "f5-tts")
    installed = get_installed_synthesizers()
    if not installed.get(target_synth, False):
        pkg_alias = _PKG_ALIASES.get(target_synth, target_synth)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Synthesizer '{target_synth}' is not installed in this environment. "
                f"To install it, run: uv sync --extra {pkg_alias} (or pip install 'epuboverlay[{pkg_alias}]')"
            ),
        )

    # Update job config with any options provided
    has_changes = False

    for key, val in [
        ("synthesizer", synthesizer),
        ("scenario", scenario),
        ("speed", speed),
        ("max_chars", max_chars),
        ("frame_rate", frame_rate),
        ("concurrency", concurrency),
        ("nfe_step", nfe_step),
        ("compile", compile),
        ("voice", voice),
        ("voice_formula", voice_formula),
        ("lang_code", lang_code),
        ("language", language),
        ("pocket_voice", pocket_voice),
        ("pocket_language", pocket_language),
        ("temp", temp),
        ("lsd_decode_steps", lsd_decode_steps),
        ("eos_threshold", eos_threshold),
        ("quantize", quantize),
        ("dialogue_voice", dialogue_voice),
        ("qwen_model", qwen_model),
        ("qwen_mode", qwen_mode),
        ("qwen_speaker", qwen_speaker),
        ("instruct", instruct),
        ("ref_text", ref_text),
    ]:
        if val is not None:
            job.config[key] = val
            has_changes = True

    if device is not None:
        job.config["device"] = device if device else None
        has_changes = True
    if noise_clamp is not None:
        job.config["noise_clamp"] = float(noise_clamp) if noise_clamp.strip() else None
        has_changes = True
    if frames_after_eos is not None:
        job.config["frames_after_eos"] = int(frames_after_eos) if frames_after_eos.strip() else None
        has_changes = True

    if ref_id and ref_id.strip():
        refs = load_references()
        ref = next((r for r in refs if r["id"] == ref_id.strip()), None)
        if not ref:
            raise HTTPException(status_code=404, detail="Selected reference voice not found")
        audio_file = REFERENCES_DIR / ref["audio_filename"]
        if not audio_file.exists():
            raise HTTPException(status_code=404, detail="Selected reference audio file not found")
        safe_ext = re.sub(r"[^.A-Za-z0-9]", "", audio_file.suffix) or ".wav"
        stored_ref_audio = job.job_dir / f"ref_audio{safe_ext}"
        shutil.copy2(audio_file, stored_ref_audio)
        job.config["ref_audio_path"] = str(stored_ref_audio)
        if target_synth == "f5-tts" and not (ref_text and ref_text.strip()):
            job.config["ref_text"] = ref.get("text", "")
        has_changes = True
    elif ref_audio and ref_audio.filename:
        ref_suffix = re.sub(r"[^.A-Za-z0-9]", "", Path(ref_audio.filename).suffix) or ".wav"
        tmp_ref = await _save_upload_to_temp(ref_audio, suffix=ref_suffix)
        try:
            stored_ref_audio = job.job_dir / f"ref_audio{ref_suffix}"
            shutil.copy2(tmp_ref, stored_ref_audio)
            job.config["ref_audio_path"] = str(stored_ref_audio)
            has_changes = True
        finally:
            tmp_ref.unlink(missing_ok=True)

    if selected_chapters is not None:
        try:
            parsed = json.loads(selected_chapters)
            if isinstance(parsed, list):
                job.config["selected_chapters"] = parsed
                has_changes = True
        except Exception:
            pass

    if has_changes:
        # Re-estimate audiobook duration if configuration has changed
        from epuboverlay.web.jobs import estimate_epub_audiobook_duration
        total_chars, est_hours = estimate_epub_audiobook_duration(
            job.input_epub_path, job.config.get("speed", 1.0)
        )
        job.total_characters = total_chars
        job.estimated_total_hours = est_hours
        job.save_to_disk()

    try:
        job_manager.start_job(job.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return job.to_dict()


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    """Download the output EPUB."""
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job is not completed yet.")
    if not job.output_epub_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found.")
    download_name = Path(job.original_filename or "output.epub").name
    if not download_name.lower().endswith(".epub"):
        download_name = f"{Path(download_name).stem}.epub"
    return FileResponse(
        path=str(job.output_epub_path),
        filename=download_name,
        media_type="application/epub+zip",
    )


@app.get("/api/jobs/{job_id}/audio/{chapter_idref}")
async def stream_chapter_audio(job_id: str, chapter_idref: str):
    """Stream per-chapter audio for in-browser playback."""
    audio_path = job_manager.get_chapter_audio_path(job_id, chapter_idref)
    if audio_path is None:
        raise HTTPException(status_code=404, detail="Chapter audio not found.")
    ext = audio_path.suffix or ".m4a"
    media_type = "audio/mp4" if ext == ".m4a" else "audio/mpeg"
    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        filename=f"{chapter_idref}{ext}",
    )


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its cache/storage."""
    if not job_manager.delete_job(job_id):
        raise HTTPException(
            status_code=400,
            detail="Job not found or is currently running.",
        )
    return {"status": "deleted"}


@app.post("/api/jobs/{job_id}/convert-audio")
async def convert_job_to_audio(
    job_id: str,
    merge: bool = Form(True),
    formats: str = Form("ass"),
    center: bool = Form(True),
    mp4_video: bool = Form(False),
    embed_subtitles: bool = Form(False),
    include_audio: bool = Form(True),
    audio_format: str = Form("m4b"),
    cover_art: UploadFile | None = File(None),
):
    """Convert a completed job's output EPUB to Audio + Subtitles (ZIP download).

    Works directly from the job's stored output EPUB — no re-upload needed.
    """
    from epuboverlay.extract import epub_to_audio_subtitles

    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job is not completed yet.")
    if not job.output_epub_path.exists():
        raise HTTPException(status_code=404, detail="Output EPUB file not found.")

    output_dir = Path(tempfile.mkdtemp(prefix="epuboverlay_convert_"))
    tmp_cover_path = None
    keep_output_dir = False

    try:
        # Save cover art if provided
        if cover_art and cover_art.filename:
            tmp_cover_path = await _save_upload_to_temp(
                cover_art, suffix=Path(cover_art.filename).suffix or ".jpg"
            )

        # Normalize audio format
        audio_fmt = audio_format.strip().lower() if audio_format else "m4b"
        if audio_fmt not in ("m4b", "m4a"):
            audio_fmt = "m4b"

        if not formats or formats.lower().strip() == "none":
            formats_list = []
        else:
            formats_list = [f.strip() for f in formats.split(",") if f.strip()]
        results = epub_to_audio_subtitles(
            epub_path=job.output_epub_path,
            output_dir=output_dir,
            merge=merge,
            formats=formats_list,
            center=center,
            mp4_video=mp4_video,
            include_audio=include_audio,
            embed_subtitles=embed_subtitles,
            cover_art=tmp_cover_path,
            audio_format=audio_fmt,
        )

        if not results:
            raise HTTPException(
                status_code=400,
                detail="No files could be extracted from the output EPUB.",
            )

        stem = Path(job.original_filename or "output").stem
        zip_name = f"{stem}_audio_subtitles"
        zip_path = output_dir / f"{zip_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for audio, subtitles in results:
                if audio:
                    zout.write(audio, audio.name)
                for sub in subtitles:
                    zout.write(sub, sub.name)

        keep_output_dir = True
        return FileResponse(
            path=str(zip_path),
            filename=f"{zip_name}.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, output_dir, ignore_errors=True),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_cover_path:
            try:
                tmp_cover_path.unlink(missing_ok=True)
            except Exception:
                pass
        if not keep_output_dir:
            shutil.rmtree(output_dir, ignore_errors=True)


@app.delete("/api/cache")
async def purge_cache():
    """Purge all caches and non-running jobs."""
    if job_manager.has_running_job():
        raise HTTPException(
            status_code=400,
            detail="Cannot purge cache while a job is running.",
        )
    job_manager.purge_all_cache()
    _PREVIEW_SYNTH_CACHE.clear()
    from epuboverlay.synthesizers.qwen3 import clear_qwen_model_cache
    clear_qwen_model_cache()
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return {"status": "purged"}


@app.get("/api/cache/size")
async def get_cache_size():
    """Get total cache size in bytes."""
    size = job_manager.get_cache_size()
    return {"size_bytes": size}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE stream for real-time job progress."""
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = job_manager.subscribe_sse(job_id)

    async def event_generator():
        try:
            # Send initial state
            initial = json.dumps(job.to_dict())
            yield f"data: {initial}\n\n"

            while True:
                try:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: queue.get(timeout=1.0)
                    )
                    yield f"data: {json.dumps(data)}\n\n"

                    # Stop streaming if job is terminal
                    status = data.get("status", "")
                    if status in ("completed", "failed", "cancelled"):
                        yield f"data: {json.dumps({'type': 'close'})}\n\n"
                        break
                except Empty:
                    # Send keepalive
                    yield ": keepalive\n\n"

                    # Check if job is done
                    current_job = job_manager.get_job(job_id)
                    if current_job and current_job.status in (
                        JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED
                    ):
                        final = json.dumps(current_job.to_dict())
                        yield f"data: {final}\n\n"
                        yield f"data: {json.dumps({'type': 'close'})}\n\n"
                        break
        finally:
            job_manager.unsubscribe_sse(job_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chapters")
async def get_chapters(epub: UploadFile = File(...)):
    """Extract chapter metadata and previews from an uploaded EPUB or other formats."""
    from epuboverlay.preprocessors import get_preprocessor
    suffix = Path(epub.filename).suffix if epub.filename else ".epub"
    tmp_path = await _save_upload_to_temp(epub, suffix=suffix)
    try:
        preprocessor = get_preprocessor(tmp_path)
        sections = preprocessor.extract_sections(tmp_path)
        return [
            {
                "idref": s.id,
                "title": s.title,
                "char_count": s.char_count,
                "preview": s.preview
            }
            for s in sections
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/api/extract")
async def extract_audio_lrc(
    epub: UploadFile = File(...),
    merge: bool = Form(True),
    formats: str = Form("ass"),
    center: bool = Form(True),
    mp4_video: bool = Form(False),
    embed_subtitles: bool = Form(False),
    include_audio: bool = Form(True),
    audio_format: str = Form("m4b"),
    cover_art: UploadFile | None = File(None),
):
    """Extract Audio + Subtitle files from an EPUB3 with Media Overlays.

    Returns a ZIP archive containing per-chapter or merged audio+subtitle pairs.
    """
    from epuboverlay.extract import epub_to_audio_subtitles

    # Save uploaded EPUB to temp file
    tmp_epub_path = await _save_upload_to_temp(epub, suffix=".epub")
    tmp_cover_path = None
    output_dir = Path(tempfile.mkdtemp(prefix="epuboverlay_extract_"))
    keep_output_dir = False

    try:
        # Save cover art if provided
        if cover_art and cover_art.filename:
            tmp_cover_path = await _save_upload_to_temp(
                cover_art, suffix=Path(cover_art.filename).suffix or ".jpg"
            )

        # Normalize audio format
        audio_fmt = audio_format.strip().lower() if audio_format else "m4b"
        if audio_fmt not in ("m4b", "m4a"):
            audio_fmt = "m4b"

        if not formats or formats.lower().strip() == "none":
            formats_list = []
        else:
            formats_list = [f.strip() for f in formats.split(",") if f.strip()]
        results = epub_to_audio_subtitles(
            epub_path=tmp_epub_path,
            output_dir=output_dir,
            merge=merge,
            formats=formats_list,
            center=center,
            mp4_video=mp4_video,
            include_audio=include_audio,
            embed_subtitles=embed_subtitles,
            cover_art=tmp_cover_path,
            audio_format=audio_fmt,
        )

        if not results:
            raise HTTPException(
                status_code=400,
                detail="No files could be extracted from the EPUB.",
            )

        # Package results into a ZIP
        zip_name = Path(epub.filename or "output").stem + "_audio_subtitles"
        zip_path = output_dir / f"{zip_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for audio, subtitles in results:
                if audio:
                    zout.write(audio, audio.name)
                for sub in subtitles:
                    zout.write(sub, sub.name)

        keep_output_dir = True
        return FileResponse(
            path=str(zip_path),
            filename=f"{zip_name}.zip",
            media_type="application/zip",
            background=BackgroundTask(shutil.rmtree, output_dir, ignore_errors=True),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            tmp_epub_path.unlink(missing_ok=True)
        except Exception:
            pass
        if tmp_cover_path:
            try:
                tmp_cover_path.unlink(missing_ok=True)
            except Exception:
                pass
        if not keep_output_dir:
            shutil.rmtree(output_dir, ignore_errors=True)


import hashlib
import asyncio

_PREVIEW_SYNTH_CACHE = {}
_PREVIEW_CACHE_LOCK = asyncio.Lock()
_MAX_CACHE_SIZE = 1


@app.post("/api/preview")
async def preview_voice(
    synthesizer: str = Form("kokoro"),
    scenario: str = Form("custom"),
    # Kokoro params
    voice: str = Form(""),
    voice_formula: str = Form(""),
    lang_code: str = Form("a"),
    language: str = Form("auto"),
    # PocketTTS params
    pocket_voice: str = Form(""),           # preset voice name
    pocket_language: str = Form("english"),
    temp: float = Form(0.7),
    lsd_decode_steps: int = Form(1),
    noise_clamp: str = Form(""),
    eos_threshold: float = Form(-4.0),
    frames_after_eos: str = Form(""),
    quantize: bool = Form(False),
    dialogue_voice: str = Form(""),
    # Qwen3 params
    qwen_model: str = Form("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
    qwen_mode: str = Form("custom_voice"),
    qwen_speaker: str = Form("Ryan"),
    instruct: str = Form(""),
    # Cloning & Reference
    ref_audio: UploadFile | None = File(None),
    ref_text: str = Form(""),
    ref_id: str = Form(""),
    # Common
    speed: float = Form(1.0),
    device: str = Form(""),
    text: str = Form("Hello, this is a preview of the selected voice."),
):
    """Generate a quick audio preview for any configured synthesizer."""
    from fastapi import Response

    if not text.strip():
        raise HTTPException(status_code=400, detail="Preview text cannot be empty.")

    # 0. Check synthesizer availability
    installed = get_installed_synthesizers()
    if not installed.get(synthesizer, False):
        pkg_alias = _PKG_ALIASES.get(synthesizer, synthesizer)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Synthesizer '{synthesizer}' is not installed in this environment. "
                f"To install it, run: uv sync --extra {pkg_alias} "
                f"(or pip install 'epuboverlay[{pkg_alias}]')"
            ),
        )

    # 0. Resolve reference voice if ref_id is provided
    resolved_ref_bytes = b""
    resolved_ref_path: Path | None = None
    resolved_ref_text = ""
    clone_capable = ("f5-tts", "pocket-tts", "qwen3-tts")
    if ref_id.strip() and synthesizer in clone_capable:
        refs = load_references()
        ref = next((r for r in refs if r["id"] == ref_id), None)
        if not ref:
            raise HTTPException(status_code=404, detail="Selected reference voice not found")
        audio_path = REFERENCES_DIR / ref["audio_filename"]
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Selected reference audio file not found")
        resolved_ref_path = audio_path
        with open(audio_path, "rb") as f:
            resolved_ref_bytes = f.read()
        resolved_ref_text = ref["text"]

    # 1. Read ref_audio bytes to compute hash if present
    ref_audio_hash = None
    ref_audio_bytes = b""
    resolved_f5_ref_text = ref_text
    if resolved_ref_bytes:
        ref_audio_bytes = resolved_ref_bytes
        ref_audio_hash = hashlib.md5(ref_audio_bytes).hexdigest()
        if not ref_text.strip() and resolved_ref_text:
            resolved_f5_ref_text = resolved_ref_text
    elif ref_audio and ref_audio.filename:
        ref_audio_bytes = await _read_upload_bytes(ref_audio)
        ref_audio_hash = hashlib.md5(ref_audio_bytes).hexdigest()

    active_ref_path: Path | None = None
    if resolved_ref_path and resolved_ref_path.exists():
        active_ref_path = resolved_ref_path
    elif ref_audio_bytes and ref_audio_hash:
        PREVIEW_UPLOADS_DIR = Path.home() / ".epuboverlay" / "cache" / "previews"
        PREVIEW_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        cached_upload = PREVIEW_UPLOADS_DIR / f"{ref_audio_hash}.wav"
        if not cached_upload.exists():
            cached_upload.write_bytes(ref_audio_bytes)
        active_ref_path = cached_upload

    parsed_noise_clamp = float(noise_clamp) if noise_clamp.strip() else None
    parsed_frames_after_eos = int(frames_after_eos) if frames_after_eos.strip() else None

    # 2. Build a unique cache key based on the settings
    cache_key = None
    if synthesizer == "kokoro":
        cache_key = ("kokoro", voice, voice_formula, lang_code, speed, device or "cpu")
    elif synthesizer == "pocket-tts":
        cache_key = (
            "pocket-tts",
            pocket_voice or "clone",
            ref_audio_hash,
            pocket_language,
            temp,
            lsd_decode_steps,
            parsed_noise_clamp,
            eos_threshold,
            parsed_frames_after_eos,
            quantize,
            dialogue_voice,
            speed,
        )
    elif synthesizer == "f5-tts":
        ref_text_hash = hashlib.md5(resolved_f5_ref_text.encode("utf-8")).hexdigest()
        cache_key = ("f5-tts", ref_audio_hash, ref_text_hash, speed, device or "cpu")
    elif synthesizer == "qwen3-tts":
        cache_key = (
            "qwen3-tts",
            qwen_model,
            qwen_mode,
            qwen_speaker,
            instruct,
            language,
            ref_audio_hash,
            resolved_f5_ref_text,
            temp,
            speed,
            device or "auto",
        )
    elif synthesizer == "dummy":
        cache_key = ("dummy", speed)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported synthesizer: {synthesizer}")

    # 3. Retrieve or build the synthesizer with thread-safe lock
    synth = None
    async with _PREVIEW_CACHE_LOCK:
        if cache_key in _PREVIEW_SYNTH_CACHE:
            synth = _PREVIEW_SYNTH_CACHE[cache_key]
            # Move to the end of dict to maintain LRU ordering
            _PREVIEW_SYNTH_CACHE.pop(cache_key)
            _PREVIEW_SYNTH_CACHE[cache_key] = synth
        else:
            # Evict existing preview synthesizers BEFORE instantiating new one to guarantee free VRAM
            while len(_PREVIEW_SYNTH_CACHE) >= _MAX_CACHE_SIZE:
                oldest_key = next(iter(_PREVIEW_SYNTH_CACHE))
                old_synth = _PREVIEW_SYNTH_CACHE.pop(oldest_key)
                del old_synth
                import gc
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass

            try:
                if synthesizer == "kokoro":
                    if not voice and not voice_formula:
                        raise HTTPException(
                            status_code=400,
                            detail="Either voice or voice_formula is required for Kokoro.",
                        )
                    from epuboverlay.synthesizers.kokoro import KokoroSynthesizer
                    synth = KokoroSynthesizer(
                        voice=voice,
                        voice_formula=voice_formula,
                        speed=speed,
                        lang_code=lang_code,
                        device=device or None,
                    )

                elif synthesizer == "pocket-tts":
                    if not pocket_voice and not active_ref_path:
                        raise HTTPException(
                            status_code=400,
                            detail="Either pocket_voice (preset) or ref_audio (clone) is required for PocketTTS.",
                        )
                    from epuboverlay.synthesizers.pocket import PocketSynthesizer
                    synth = PocketSynthesizer(
                        voice=pocket_voice,
                        ref_audio=active_ref_path,
                        speed=speed,
                        pocket_language=pocket_language,
                        temp=temp,
                        lsd_decode_steps=lsd_decode_steps,
                        noise_clamp=parsed_noise_clamp,
                        eos_threshold=eos_threshold,
                        frames_after_eos=parsed_frames_after_eos,
                        quantize=quantize,
                        dialogue_voice=dialogue_voice,
                    )

                elif synthesizer == "f5-tts":
                    if not active_ref_path:
                        raise HTTPException(
                            status_code=400,
                            detail="ref_audio is required for F5-TTS preview.",
                        )
                    if not resolved_f5_ref_text.strip():
                        raise HTTPException(
                            status_code=400,
                            detail="ref_text is required for F5-TTS preview.",
                        )
                    from epuboverlay.synthesizers.f5tts import F5TTSSynthesizer
                    synth = F5TTSSynthesizer(
                        ref_audio=active_ref_path,
                        ref_text=resolved_f5_ref_text,
                        device=device or None,
                        speed=speed,
                    )

                elif synthesizer == "qwen3-tts":
                    if qwen_mode == "clone" and not active_ref_path:
                        raise HTTPException(
                            status_code=400,
                            detail="ref_audio (or saved ref_id) is required for Qwen3-TTS clone mode.",
                        )
                    from epuboverlay.synthesizers.qwen3 import Qwen3TTSSynthesizer
                    synth = Qwen3TTSSynthesizer(
                        model_name=qwen_model,
                        mode=qwen_mode,
                        speaker=qwen_speaker,
                        instruct=instruct,
                        language=language,
                        ref_audio=active_ref_path,
                        ref_text=resolved_f5_ref_text,
                        speed=speed,
                        temp=temp,
                        device=device or None,
                    )

                elif synthesizer == "dummy":
                    from epuboverlay.synthesizers.dummy import DummySynthesizer
                    synth = DummySynthesizer()

            except Exception as e:
                # If OOM happened during initialization, purge all GPU caches and re-raise cleanly
                if "CUDA out of memory" in str(e) or "OutOfMemoryError" in type(e).__name__:
                    _PREVIEW_SYNTH_CACHE.clear()
                    from epuboverlay.synthesizers.qwen3 import clear_qwen_model_cache
                    clear_qwen_model_cache()
                    import gc
                    gc.collect()
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception:
                        pass
                    raise HTTPException(
                        status_code=503,
                        detail="CUDA out of memory on GPU. VRAM has been cleared. Please retry with a shorter prompt or use the 0.6B Base model.",
                    ) from e
                raise

            # Save model to cache
            _PREVIEW_SYNTH_CACHE[cache_key] = synth

    # 4. Perform synthesis
    try:
        from epuboverlay.normalization import normalize_text
        norm_settings = dict(load_settings_data().get("current_settings", {}))
        norm_settings["language"] = language if language != "auto" else (pocket_language if synthesizer == "pocket-tts" else lang_code)
        normalized_text = normalize_text(text, norm_settings)
        
        wav_bytes, _ = synth.synthesize(normalized_text)
        
        # Save to playground stack in RAM
        import time
        audio_id = f"pg_{int(time.time() * 1000)}"
        
        settings_dict = {
            "speed": speed,
            "device": device or "cpu",
            "scenario": scenario,
        }
        if synthesizer == "kokoro":
            settings_dict["voice"] = voice
            settings_dict["voice_formula"] = voice_formula
            settings_dict["lang_code"] = lang_code
        elif synthesizer == "pocket-tts":
            settings_dict["pocket_voice"] = pocket_voice
            settings_dict["pocket_language"] = pocket_language
            settings_dict["temp"] = temp
            settings_dict["lsd_decode_steps"] = lsd_decode_steps
            settings_dict["mode"] = "preset" if pocket_voice else "clone"
            if ref_id:
                settings_dict["ref_id"] = ref_id
        elif synthesizer == "qwen3-tts":
            settings_dict["mode"] = qwen_mode
            settings_dict["speaker"] = qwen_speaker
            settings_dict["language"] = language
            if instruct:
                settings_dict["instruct"] = instruct
        elif synthesizer == "f5-tts":
            settings_dict["mode"] = "clone"
            if ref_id:
                settings_dict["ref_id"] = ref_id
        elif synthesizer == "dummy":
            settings_dict["mode"] = "dummy"
                
        _PLAYGROUND_HISTORY.insert(0, {
            "id": audio_id,
            "timestamp": time.time(),
            "synthesizer": synthesizer,
            "text": text,
            "settings": settings_dict,
            "audio_bytes": wav_bytes,
        })
        
        # Cap stack size at 100
        if len(_PLAYGROUND_HISTORY) > 100:
            _PLAYGROUND_HISTORY.pop()

        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        if "CUDA out of memory" in str(e) or "OutOfMemoryError" in type(e).__name__:
            _PREVIEW_SYNTH_CACHE.clear()
            from epuboverlay.synthesizers.qwen3 import clear_qwen_model_cache
            clear_qwen_model_cache()
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            raise HTTPException(
                status_code=503,
                detail="CUDA out of memory on GPU during generation. GPU memory has been flushed. Please retry with a shorter prompt or use the 0.6B Base model.",
            ) from e
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Preview synthesis failed: {str(e)}"
        )



def main():
    """Entry point for the epuboverlay-web command."""
    import uvicorn

    parser = argparse.ArgumentParser(description="epuboverlay Web Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind to (default: 8765)")
    parser.add_argument("--data-dir", type=Path, help="Directory for job data (default: ~/.epuboverlay/jobs)")
    args = parser.parse_args()

    if args.data_dir:
        global job_manager
        job_manager = JobManager(data_dir=args.data_dir)

    print(f"🎧 epuboverlay Dashboard starting at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
