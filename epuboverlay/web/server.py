"""FastAPI web server for epuboverlay dashboard."""
from __future__ import annotations

import argparse
import asyncio
import json
import psutil
import subprocess
import sys
import tempfile
from pathlib import Path
from queue import Empty

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from epuboverlay.pipeline import (
    DummySynthesizer,
    F5TTSSynthesizer,
    generate_media_overlay_epub,
)
from epuboverlay.progress import ProgressEvent
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


@app.get("/api/config")
async def get_config():
    """Return available synthesizers and defaults."""
    return {
        "synthesizers": ["f5-tts", "dummy"],
        "defaults": {
            "synthesizer": "f5-tts",
            "speed": 1.0,
            "max_chars": 150,
            "frame_rate": 24000.0,
        },
    }


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
):
    """Submit a new EPUB overlay generation job."""
    if job_manager.has_running_job():
        raise HTTPException(
            status_code=409,
            detail="A job is already running. Please wait for it to complete or cancel it.",
        )

    if synthesizer == "f5-tts":
        if not ref_audio or not ref_text:
            raise HTTPException(
                status_code=400,
                detail="ref_audio and ref_text are required for f5-tts synthesizer.",
            )

    # Save uploaded EPUB to temp file
    tmp_epub = tempfile.NamedTemporaryFile(delete=False, suffix=".epub")
    content = await epub.read()
    tmp_epub.write(content)
    tmp_epub.close()

    config = {
        "synthesizer": synthesizer,
        "ref_text": ref_text,
        "device": device or None,
        "speed": speed,
        "max_chars": max_chars,
        "frame_rate": frame_rate,
    }

    # Save ref audio if provided
    ref_audio_path = None
    if ref_audio and synthesizer == "f5-tts":
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

    def run_pipeline(job: Job):
        """Execute the pipeline in a background thread."""
        cfg = job.config

        if cfg["synthesizer"] == "f5-tts":
            synth = F5TTSSynthesizer(
                ref_audio=cfg["ref_audio_path"],
                ref_text=cfg["ref_text"],
                device=cfg.get("device"),
                speed=cfg["speed"],
            )
        else:
            synth = DummySynthesizer(sample_rate=int(cfg["frame_rate"]))

        def progress_cb(event: ProgressEvent):
            job_manager.update_job_progress(job.id, event)

        def chapter_audio_cb(idref: str, mp3_path: Path):
            job_manager.add_chapter_audio(job.id, idref, mp3_path)

        generate_media_overlay_epub(
            input_epub=job.input_epub_path,
            output_epub=job.output_epub_path,
            synthesizer=synth,
            frame_rate_hz=cfg["frame_rate"],
            max_chars=cfg["max_chars"],
            progress_callback=progress_cb,
            cancel_event=job.cancel_event,
            chapter_audio_callback=chapter_audio_cb,
        )

    job_manager.start_job(job.id, run_pipeline)

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
    """Stream per-chapter MP3 for in-browser playback."""
    mp3_path = job_manager.get_chapter_audio_path(job_id, chapter_idref)
    if mp3_path is None:
        raise HTTPException(status_code=404, detail="Chapter audio not found.")
    return FileResponse(
        path=str(mp3_path),
        media_type="audio/mpeg",
        filename=f"{chapter_idref}.mp3",
    )


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
