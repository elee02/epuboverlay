"""FastAPI web server for epuboverlay dashboard."""
from __future__ import annotations

import argparse
import asyncio
import json
import psutil
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from queue import Empty

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Synthesizer imports moved to jobs.py runner process
from epuboverlay.web.jobs import JobManager, Job, JobStatus

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="epuboverlay Dashboard", version="0.1.0")
job_manager = JobManager()

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
        return {"current_settings": DEFAULT_SETTINGS.copy(), "profiles": {}}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "current_settings" not in data:
                data["current_settings"] = DEFAULT_SETTINGS.copy()
            else:
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data["current_settings"]:
                        data["current_settings"][k] = v
            if "profiles" not in data:
                data["profiles"] = {}
            return data
    except Exception:
        return {"current_settings": DEFAULT_SETTINGS.copy(), "profiles": {}}

def save_settings_data(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@app.get("/api/config")
async def get_config():
    """Return available synthesizers and defaults."""
    from epuboverlay.synthesizers import KOKORO_VOICES
    data = load_settings_data()
    current = data.get("current_settings", {})
    
    defaults = {
        "synthesizer": current.get("synthesizer", "f5-tts"),
        "speed": current.get("speed", 1.0),
        "max_chars": current.get("max_chars", 150),
        "frame_rate": current.get("frame_rate", 24000.0),
        "concurrency": current.get("concurrency", 2),
        "nfe_step": current.get("nfe_step", 32),
        "compile": current.get("compile", False),
        "voice": current.get("voice", "af_heart"),
        "voice_formula": current.get("voice_formula", ""),
        "lang_code": current.get("lang_code", "a"),
        "device": current.get("device", ""),
    }
    
    return {
        "synthesizers": ["f5-tts", "kokoro", "pocket-tts", "dummy"],
        "kokoro_voices": KOKORO_VOICES,
        "defaults": defaults,
    }


@app.get("/api/settings")
async def get_settings():
    """Get the current settings and profiles."""
    return load_settings_data()


from fastapi import Body

@app.post("/api/settings")
async def save_settings(settings: dict = Body(...)):
    """Save current settings."""
    data = load_settings_data()
    data["current_settings"] = settings
    save_settings_data(data)
    return {"status": "saved", "settings": data["current_settings"]}


@app.post("/api/profiles")
async def save_profile(profile_data: dict = Body(...)):
    """Save a settings profile."""
    name = profile_data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required.")
    
    settings = profile_data.get("settings", {})
    if not settings:
        raise HTTPException(status_code=400, detail="Profile settings are required.")
        
    data = load_settings_data()
    data["profiles"][name] = settings
    save_settings_data(data)
    return {"status": "saved", "profiles": data["profiles"]}


@app.delete("/api/profiles/{name}")
async def delete_profile(name: str):
    """Delete a profile."""
    data = load_settings_data()
    if name in data["profiles"]:
        del data["profiles"][name]
        save_settings_data(data)
        return {"status": "deleted", "profiles": data["profiles"]}
    raise HTTPException(status_code=404, detail=f"Profile '{name}' not found.")



@app.get("/api/jobs")
async def list_jobs():
    """List all jobs."""
    return [job.to_dict() for job in job_manager.list_jobs()]


@app.post("/api/jobs")
async def create_job(
    epub: UploadFile = File(...),
    synthesizer: str = Form("f5-tts"),
    ref_audio: UploadFile | None = File(None),
    ref_text: str = Form(""),
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
    selected_chapters: str = Form(""),  # JSON array of idref strings
):
    """Submit a new EPUB overlay generation job."""
    if job_manager.has_running_job():
        raise HTTPException(
            status_code=409,
            detail="A job is already running. Please wait for it to complete or cancel it.",
        )

    # Validate based on selected synthesizer
    if synthesizer == "f5-tts":
        if not ref_audio or not ref_text:
            raise HTTPException(
                status_code=400,
                detail="ref_audio and ref_text are required for f5-tts synthesizer.",
            )
    elif synthesizer == "pocket-tts":
        if not ref_audio:
            raise HTTPException(
                status_code=400,
                detail="ref_audio is required for pocket-tts synthesizer.",
            )
    elif synthesizer == "kokoro":
        if not voice and not voice_formula:
            raise HTTPException(
                status_code=400,
                detail="Either voice or voice_formula is required for kokoro synthesizer.",
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

    # Save uploaded EPUB to temp file
    tmp_epub = tempfile.NamedTemporaryFile(delete=False, suffix=".epub")
    content = await epub.read()
    tmp_epub.write(content)
    tmp_epub.close()

    norm_settings = load_settings_data().get("current_settings", {})

    config = {
        "synthesizer": synthesizer,
        "ref_text": ref_text,
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
        "selected_chapters": parsed_chapters,
        "expand_numerals": norm_settings.get("expand_numerals", True),
        "resolve_contractions": norm_settings.get("resolve_contractions", True),
        "resolve_heteronyms": norm_settings.get("resolve_heteronyms", True),
        "harmonize_punctuation": norm_settings.get("harmonize_punctuation", True),
        "custom_lexicon": norm_settings.get("custom_lexicon", []),
    }

    # Save ref audio if provided (only for models that require voice cloning)
    ref_audio_path = None
    if ref_audio and synthesizer in ("f5-tts", "pocket-tts"):
        ref_audio_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        ref_audio_content = await ref_audio.read()
        ref_audio_tmp.write(ref_audio_content)
        ref_audio_tmp.close()
        ref_audio_path = Path(ref_audio_tmp.name)
        config["ref_audio_path"] = str(ref_audio_path)

    try:
        job = job_manager.create_job(
            input_epub_path=Path(tmp_epub.name),
            original_filename=epub.filename or "output.epub",
            config=config,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

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

    # Update job config with any options provided
    has_changes = False

    if synthesizer is not None:
        job.config["synthesizer"] = synthesizer
        has_changes = True
    if device is not None:
        job.config["device"] = device if device else None
        has_changes = True
    if speed is not None:
        job.config["speed"] = speed
        has_changes = True
    if max_chars is not None:
        job.config["max_chars"] = max_chars
        has_changes = True
    if frame_rate is not None:
        job.config["frame_rate"] = frame_rate
        has_changes = True
    if concurrency is not None:
        job.config["concurrency"] = concurrency
        has_changes = True
    if nfe_step is not None:
        job.config["nfe_step"] = nfe_step
        has_changes = True
    if compile is not None:
        job.config["compile"] = compile
        has_changes = True
    if voice is not None:
        job.config["voice"] = voice
        has_changes = True
    if voice_formula is not None:
        job.config["voice_formula"] = voice_formula
        has_changes = True
    if lang_code is not None:
        job.config["lang_code"] = lang_code
        has_changes = True
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
    return FileResponse(
        path=str(job.output_epub_path),
        filename=job.original_filename,
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
    merge: bool = Form(False),
):
    """Convert a completed job's output EPUB to Audio + LRC (ZIP download).

    Works directly from the job's stored output EPUB — no re-upload needed.
    """
    from epuboverlay.extract import epub_to_mp3_lrc

    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Job is not completed yet.")
    if not job.output_epub_path.exists():
        raise HTTPException(status_code=404, detail="Output EPUB file not found.")

    output_dir = Path(tempfile.mkdtemp(prefix="epuboverlay_convert_"))

    try:
        results = epub_to_mp3_lrc(
            epub_path=job.output_epub_path,
            output_dir=output_dir,
            merge=merge,
        )

        if not results:
            raise HTTPException(
                status_code=400,
                detail="No audio overlays found in the output EPUB.",
            )

        stem = Path(job.original_filename or "output").stem
        zip_name = f"{stem}_audio_lrc"
        zip_path = output_dir / f"{zip_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for audio, lrc in results:
                zout.write(audio, audio.name)
                zout.write(lrc, lrc.name)

        return FileResponse(
            path=str(zip_path),
            filename=f"{zip_name}.zip",
            media_type="application/zip",
        )

    except (ValueError, HTTPException):
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/cache")
async def purge_cache():
    """Purge all caches and non-running jobs."""
    if job_manager.has_running_job():
        raise HTTPException(
            status_code=400,
            detail="Cannot purge cache while a job is running.",
        )
    job_manager.purge_all_cache()
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
    """Extract chapter metadata and previews from an uploaded EPUB."""
    from epuboverlay.pipeline import extract_chapter_previews
    tmp_epub = tempfile.NamedTemporaryFile(delete=False, suffix=".epub")
    try:
        content = await epub.read()
        tmp_epub.write(content)
        tmp_epub.close()

        previews = extract_chapter_previews(Path(tmp_epub.name))
        return previews
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            Path(tmp_epub.name).unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/api/extract")
async def extract_audio_lrc(
    epub: UploadFile = File(...),
    merge: bool = Form(False),
):
    """Extract Audio + LRC files from an EPUB3 with Media Overlays.

    Returns a ZIP archive containing per-chapter or merged audio+LRC pairs.
    """
    from epuboverlay.extract import epub_to_mp3_lrc

    # Save uploaded EPUB to temp file
    tmp_epub = tempfile.NamedTemporaryFile(delete=False, suffix=".epub")
    content = await epub.read()
    tmp_epub.write(content)
    tmp_epub.close()

    # Create temp output directory
    output_dir = Path(tempfile.mkdtemp(prefix="epuboverlay_extract_"))

    try:
        results = epub_to_mp3_lrc(
            epub_path=Path(tmp_epub.name),
            output_dir=output_dir,
            merge=merge,
        )

        if not results:
            raise HTTPException(
                status_code=400,
                detail="No audio overlays found in the EPUB.",
            )

        # Package results into a ZIP
        zip_name = Path(epub.filename or "output").stem + "_audio_lrc"
        zip_path = output_dir / f"{zip_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for audio, lrc in results:
                zout.write(audio, audio.name)
                zout.write(lrc, lrc.name)

        return FileResponse(
            path=str(zip_path),
            filename=f"{zip_name}.zip",
            media_type="application/zip",
            background=None,  # Don't clean up immediately
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp epub
        try:
            Path(tmp_epub.name).unlink(missing_ok=True)
        except Exception:
            pass
        # Note: output_dir cleanup is deferred — FileResponse needs the file.
        # FastAPI/Starlette will handle response completion.


@app.post("/api/preview")
async def preview_voice(
    voice: str = Form(""),
    voice_formula: str = Form(""),
    lang_code: str = Form("a"),
    text: str = Form("Hello, this is a preview of the selected voice mix."),
):
    """Generate a quick audio preview of a voice or blend formula."""
    from fastapi import Response

    if not voice and not voice_formula:
        raise HTTPException(
            status_code=400,
            detail="Either voice or voice_formula is required.",
        )
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Preview text cannot be empty.",
        )

    try:
        from epuboverlay.synthesizers.kokoro import KokoroSynthesizer

        # We instantiate KokoroSynthesizer on CPU for preview
        synth = KokoroSynthesizer(
            voice=voice,
            voice_formula=voice_formula,
            speed=1.0,
            lang_code=lang_code,
            device="cpu",
        )

        wav_bytes, _ = synth.synthesize(text)
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
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
