"""Job manager for epuboverlay web dashboard — single-job, thread-safe."""
from __future__ import annotations

import json
import os
import psutil
import shutil
import signal
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Callable
import multiprocessing

_mp_ctx = multiprocessing.get_context("spawn")


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ChapterAudio:
    """Represents a completed chapter's audio file available for preview."""
    idref: str
    mp3_path: Path
    completed_at: float = 0.0


@dataclass
class Job:
    """Represents a single EPUB overlay generation job."""
    id: str
    input_epub_path: Path
    output_epub_path: Path
    original_filename: str
    book_title: str = ""
    status: JobStatus = JobStatus.QUEUED
    config: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    chapter_audios: list[ChapterAudio] = field(default_factory=list)
    cancel_event: Any = field(default_factory=lambda: _mp_ctx.Event())

    # Live progress fields — updated by progress callback
    current_phase: str = ""
    chapter_index: int = 0
    chapter_total: int = 0
    chapter_name: str = ""
    chunk_index: int = 0
    chunk_total: int = 0
    elapsed_seconds: float = 0.0
    message: str = ""
    overall_percent: float = 0.0

    # Audiobook size and chunk ETA fields
    total_characters: int = 0
    estimated_total_hours: float = 0.0
    audiobook_duration_seconds: float = 0.0
    total_chunks_to_synthesize: int = 0
    chunks_processed_so_far: int = 0
    synthesis_elapsed_seconds: float = 0.0

    @property
    def job_dir(self) -> Path:
        return self.input_epub_path.parent

    @property
    def estimated_remaining_seconds(self) -> float | None:
        """Calculate faithful remaining seconds based on average time per chunk."""
        if self.status == JobStatus.COMPLETED:
            return 0.0
        if self.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            return None
        if self.chunks_processed_so_far > 0 and self.total_chunks_to_synthesize > 0:
            if self.chunks_processed_so_far >= self.total_chunks_to_synthesize:
                return 5.0  # nominal estimate for final packaging
            avg_time_per_chunk = self.synthesis_elapsed_seconds / self.chunks_processed_so_far
            remaining_chunks = self.total_chunks_to_synthesize - self.chunks_processed_so_far
            return remaining_chunks * avg_time_per_chunk
        return None

    def save_to_disk(self) -> None:
        """Save job state to job.json in its directory."""
        try:
            job_file = self.job_dir / "job.json"
            data = self.to_serialize_dict()
            temp_file = job_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(job_file)
        except Exception as e:
            print(f"Error saving job {self.id} to disk: {e}")

    def to_serialize_dict(self) -> dict:
        """Return a dictionary representing the job suitable for JSON serialization."""
        return {
            "id": self.id,
            "input_epub_path": str(self.input_epub_path),
            "output_epub_path": str(self.output_epub_path),
            "original_filename": self.original_filename,
            "book_title": self.book_title,
            "status": self.status.value,
            "config": self.config,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "total_characters": self.total_characters,
            "estimated_total_hours": self.estimated_total_hours,
            "audiobook_duration_seconds": self.audiobook_duration_seconds,
            "progress": {
                "phase": self.current_phase,
                "chapter_index": self.chapter_index,
                "chapter_total": self.chapter_total,
                "chapter_name": self.chapter_name,
                "chunk_index": self.chunk_index,
                "chunk_total": self.chunk_total,
                "elapsed_seconds": self.elapsed_seconds,
                "message": self.message,
                "overall_percent": self.overall_percent,
                "total_chunks_to_synthesize": self.total_chunks_to_synthesize,
                "chunks_processed_so_far": self.chunks_processed_so_far,
                "synthesis_elapsed_seconds": self.synthesis_elapsed_seconds,
                "estimated_remaining_seconds": self.estimated_remaining_seconds,
            },
            "chapter_audios": [
                {
                    "idref": ca.idref,
                    "mp3_path": str(ca.mp3_path),
                    "completed_at": ca.completed_at
                }
                for ca in self.chapter_audios
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        """Reconstruct a Job object from a dictionary."""
        job = cls(
            id=data["id"],
            input_epub_path=Path(data["input_epub_path"]),
            output_epub_path=Path(data["output_epub_path"]),
            original_filename=data["original_filename"],
            book_title=data.get("book_title", ""),
            status=JobStatus(data.get("status", "queued")),
            config=data.get("config", {}),
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at", 0.0),
            completed_at=data.get("completed_at", 0.0),
            error=data.get("error", ""),
            total_characters=data.get("total_characters", 0),
            estimated_total_hours=data.get("estimated_total_hours", 0.0),
            audiobook_duration_seconds=data.get("audiobook_duration_seconds", 0.0),
        )
        progress = data.get("progress", {})
        job.current_phase = progress.get("phase", "")
        job.chapter_index = progress.get("chapter_index", 0)
        job.chapter_total = progress.get("chapter_total", 0)
        job.chapter_name = progress.get("chapter_name", "")
        job.chunk_index = progress.get("chunk_index", 0)
        job.chunk_total = progress.get("chunk_total", 0)
        job.elapsed_seconds = progress.get("elapsed_seconds", 0.0)
        job.message = progress.get("message", "")
        job.overall_percent = progress.get("overall_percent", 0.0)
        job.total_chunks_to_synthesize = progress.get("total_chunks_to_synthesize", 0)
        job.chunks_processed_so_far = progress.get("chunks_processed_so_far", 0)
        job.synthesis_elapsed_seconds = progress.get("synthesis_elapsed_seconds", 0.0)

        job.chapter_audios = [
            ChapterAudio(
                idref=ca["idref"],
                mp3_path=Path(ca["mp3_path"]),
                completed_at=ca.get("completed_at", 0.0)
            )
            for ca in data.get("chapter_audios", [])
        ]
        return job

    def to_dict(self) -> dict:
        """Serialize job state for JSON API responses."""
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "book_title": self.book_title,
            "status": self.status.value,
            "config": self.config,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "total_characters": self.total_characters,
            "estimated_total_hours": self.estimated_total_hours,
            "audiobook_duration_seconds": self.audiobook_duration_seconds,
            "progress": {
                "phase": self.current_phase,
                "chapter_index": self.chapter_index,
                "chapter_total": self.chapter_total,
                "chapter_name": self.chapter_name,
                "chunk_index": self.chunk_index,
                "chunk_total": self.chunk_total,
                "elapsed_seconds": round(self.elapsed_seconds, 2),
                "message": self.message,
                "overall_percent": round(self.overall_percent, 1),
                "total_chunks_to_synthesize": self.total_chunks_to_synthesize,
                "chunks_processed_so_far": self.chunks_processed_so_far,
                "synthesis_elapsed_seconds": round(self.synthesis_elapsed_seconds, 2),
                "estimated_remaining_seconds": round(self.estimated_remaining_seconds, 2) if self.estimated_remaining_seconds is not None else None,
            },
            "chapter_audios": [
                {"idref": ca.idref, "completed_at": ca.completed_at}
                for ca in self.chapter_audios
            ],
        }


def estimate_epub_audiobook_duration(epub_path: Path, speed: float = 1.0) -> tuple[int, float]:
    """Calculate the total character count and estimated audiobook duration of an EPUB."""
    total_chars = 0
    try:
        with zipfile.ZipFile(epub_path) as zf:
            container_xml = zf.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                return 0, 0.0

            opf_path = rootfile.attrib.get("full-path", "")
            if not opf_path:
                return 0, 0.0

            opf_root = ET.fromstring(zf.read(opf_path))
            manifest_node = opf_root.find(".//{*}manifest")
            spine_node = opf_root.find(".//{*}spine")
            if manifest_node is None or spine_node is None:
                return 0, 0.0

            manifest_items = {}
            for item in manifest_node.findall(".//{*}item"):
                item_id = item.attrib.get("id")
                if item_id:
                    manifest_items[item_id] = item

            spine_itemrefs = spine_node.findall(".//{*}itemref")
            opf_dir = Path(opf_path).parent

            from html.parser import HTMLParser
            class SimpleTextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text_parts = []
                def handle_data(self, data):
                    stripped = data.strip()
                    if stripped:
                        self.text_parts.append(stripped)
                def get_text(self):
                    return " ".join(self.text_parts)

            for itemref in spine_itemrefs:
                idref = itemref.attrib.get("idref")
                item = manifest_items.get(idref or "")
                if item is None:
                    continue
                media_type = item.attrib.get("media-type")
                if media_type != "application/xhtml+xml":
                    continue
                href = item.attrib.get("href")
                
                # Normalize zip path
                zip_href = (opf_dir / href).as_posix()
                zip_href = os.path.normpath(zip_href)
                if zip_href.startswith("."):
                    zip_href = zip_href.lstrip("./")
                try:
                    content_bytes = zf.read(zip_href)
                    content_str = content_bytes.decode("utf-8", errors="ignore")
                    extractor = SimpleTextExtractor()
                    extractor.feed(content_str)
                    total_chars += len(extractor.get_text())
                except Exception:
                    pass
    except Exception:
        pass

    chars_per_sec = 15.0 * speed
    duration_seconds = total_chars / chars_per_sec if chars_per_sec > 0 else 0
    duration_hours = duration_seconds / 3600.0
    return total_chars, duration_hours


def extract_epub_title(epub_path: Path) -> str:
    """Extract book title from EPUB metadata, returning filename if not found."""
    try:
        with zipfile.ZipFile(epub_path) as zf:
            container_xml = zf.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                return epub_path.stem

            opf_path = rootfile.attrib.get("full-path", "")
            if not opf_path:
                return epub_path.stem

            opf_root = ET.fromstring(zf.read(opf_path))
            title_el = opf_root.find(".//{*}title")
            if title_el is not None and title_el.text:
                return title_el.text.strip()
    except Exception:
        pass
    return epub_path.stem


def run_job_process(
    job_id: str,
    input_epub_path: Path,
    output_epub_path: Path,
    config: dict,
    cancel_event: Any,
    progress_queue: multiprocessing.Queue,
) -> None:
    """Target function executed in the child process."""
    try:
        from epuboverlay.pipeline import F5TTSSynthesizer, DummySynthesizer, generate_media_overlay_epub
        from epuboverlay.progress import ProgressEvent

        if config["synthesizer"] == "f5-tts":
            synth = F5TTSSynthesizer(
                ref_audio=config["ref_audio_path"],
                ref_text=config["ref_text"],
                device=config.get("device"),
                speed=config["speed"],
                nfe_step=config.get("nfe_step", 32),
                compile=config.get("compile", False),
            )
        else:
            synth = DummySynthesizer(sample_rate=int(config["frame_rate"]))

        def progress_cb(event: ProgressEvent):
            event_dict = {
                "phase": event.phase,
                "chapter_index": event.chapter_index,
                "chapter_total": event.chapter_total,
                "chapter_name": event.chapter_name,
                "chunk_index": event.chunk_index,
                "chunk_total": event.chunk_total,
                "elapsed_seconds": event.elapsed_seconds,
                "message": event.message,
                "overall_percent": event.overall_percent,
                "total_chunks_to_synthesize": event.total_chunks_to_synthesize,
                "chunks_processed_so_far": event.chunks_processed_so_far,
                "synthesis_elapsed_seconds": event.synthesis_elapsed_seconds,
                "total_characters": event.total_characters,
                "estimated_total_hours": event.estimated_total_hours,
                "audiobook_duration_seconds": event.audiobook_duration_seconds,
            }
            progress_queue.put(("progress", job_id, event_dict))

        def chapter_audio_cb(idref: str, mp3_path: Path):
            progress_queue.put(("chapter_audio", job_id, (idref, str(mp3_path))))

        generate_media_overlay_epub(
            input_epub=input_epub_path,
            output_epub=output_epub_path,
            synthesizer=synth,
            frame_rate_hz=config["frame_rate"],
            max_chars=config["max_chars"],
            progress_callback=progress_cb,
            cancel_event=cancel_event,
            chapter_audio_callback=chapter_audio_cb,
            concurrency=config.get("concurrency", 2),
        )
        progress_queue.put(("completed", job_id, None))
    except Exception as e:
        import traceback
        traceback.print_exc()
        progress_queue.put(("failed", job_id, str(e)))


class JobManager:
    """Manages job lifecycle — single-job at a time."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or Path.home() / ".epuboverlay" / "jobs"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._active_processes: dict[str, multiprocessing.Process] = {}
        self._sse_queues: dict[str, list[Queue]] = {}  # job_id -> list of subscriber queues
        
        self._mp_queue = _mp_ctx.Queue()
        self._reader_thread = threading.Thread(target=self._queue_reader, daemon=True)
        self._reader_thread.start()
        
        self._load_jobs_from_disk()

    def _queue_reader(self) -> None:
        while True:
            try:
                msg = self._mp_queue.get()
                if msg is None:
                    break
                event_type, job_id, payload = msg
                self._handle_mp_event(event_type, job_id, payload)
            except Exception as e:
                print(f"Error in queue reader thread: {e}")
                time.sleep(0.1)

    def _handle_mp_event(self, event_type: str, job_id: str, payload: Any) -> None:
        job = self.get_job(job_id)
        if job is None:
            return

        if event_type == "progress":
            job.current_phase = payload.get("phase", "")
            job.chapter_index = payload.get("chapter_index", 0)
            job.chapter_total = payload.get("chapter_total", 0)
            job.chapter_name = payload.get("chapter_name", "")
            job.chunk_index = payload.get("chunk_index", 0)
            job.chunk_total = payload.get("chunk_total", 0)
            job.elapsed_seconds = payload.get("elapsed_seconds", 0.0)
            job.message = payload.get("message", "")
            job.overall_percent = payload.get("overall_percent", 0.0)
            job.total_chunks_to_synthesize = payload.get("total_chunks_to_synthesize", 0)
            job.chunks_processed_so_far = payload.get("chunks_processed_so_far", 0)
            job.synthesis_elapsed_seconds = payload.get("synthesis_elapsed_seconds", 0.0)
            
            if payload.get("total_characters", 0) > 0:
                job.total_characters = payload.get("total_characters", 0)
            if payload.get("estimated_total_hours", 0.0) > 0:
                job.estimated_total_hours = payload.get("estimated_total_hours", 0.0)
            if payload.get("audiobook_duration_seconds", 0.0) > 0:
                job.audiobook_duration_seconds = payload.get("audiobook_duration_seconds", 0.0)
                
            self._push_sse(job_id, job)

        elif event_type == "chapter_audio":
            idref, mp3_path_str = payload
            self.add_chapter_audio(job_id, idref, Path(mp3_path_str))

        elif event_type == "completed":
            with self._lock:
                job.status = JobStatus.COMPLETED
                job.completed_at = time.time()
                self._active_processes.pop(job_id, None)
            job.save_to_disk()
            self._push_sse(job_id, job)

        elif event_type == "failed":
            error_msg = payload
            with self._lock:
                if job.status != JobStatus.CANCELLED:
                    job.status = JobStatus.FAILED
                    job.error = error_msg
                job.completed_at = time.time()
                self._active_processes.pop(job_id, None)
            job.save_to_disk()
            self._push_sse(job_id, job)

    def _load_jobs_from_disk(self) -> None:
        """Scan data_dir, load existing job.json files, and correct stuck states."""
        try:
            for job_dir in self._data_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                job_json = job_dir / "job.json"
                if not job_json.exists():
                    continue
                try:
                    with open(job_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    job = Job.from_dict(data)
                    
                    if job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
                        job.status = JobStatus.FAILED
                        job.error = "Server restarted during execution."
                        job.completed_at = time.time()
                        job.save_to_disk()
                        
                    self._jobs[job.id] = job
                    self._sse_queues[job.id] = []
                except Exception as e:
                    print(f"Error loading job from {job_json}: {e}")
        except Exception as e:
            print(f"Error scanning jobs directory {self._data_dir}: {e}")

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def has_running_job(self) -> bool:
        """Check if there's currently a running job."""
        with self._lock:
            return any(j.status == JobStatus.RUNNING for j in self._jobs.values())

    def create_job(
        self,
        input_epub_path: Path,
        original_filename: str,
        config: dict,
    ) -> Job:
        """Create a new job. Raises RuntimeError if a job is already running."""
        if self.has_running_job():
            raise RuntimeError("A job is already running. Please wait or cancel it first.")

        job_id = str(uuid.uuid4())[:8]
        job_dir = self._data_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # Copy input epub to job directory
        stored_epub = job_dir / "input.epub"
        shutil.copy2(input_epub_path, stored_epub)

        # Copy reference audio if provided in config
        ref_audio_path_str = config.get("ref_audio_path")
        if ref_audio_path_str:
            ref_audio_path = Path(ref_audio_path_str)
            if ref_audio_path.exists():
                stored_ref_audio = job_dir / f"ref_audio{ref_audio_path.suffix}"
                shutil.copy2(ref_audio_path, stored_ref_audio)
                config["ref_audio_path"] = str(stored_ref_audio)

        output_epub = job_dir / f"output_{original_filename}"
        audio_dir = job_dir / "audio"
        audio_dir.mkdir(exist_ok=True)

        book_title = extract_epub_title(stored_epub)
        total_chars, est_hours = estimate_epub_audiobook_duration(stored_epub, config.get("speed", 1.0))

        job = Job(
            id=job_id,
            input_epub_path=stored_epub,
            output_epub_path=output_epub,
            original_filename=original_filename,
            book_title=book_title,
            config=config,
            total_characters=total_chars,
            estimated_total_hours=est_hours,
        )

        with self._lock:
            self._jobs[job_id] = job
            self._sse_queues[job_id] = []

        job.save_to_disk()
        return job

    def start_job(self, job_id: str) -> None:
        """Start a job in a background subprocess."""
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        job.cancel_event.clear()

        with self._lock:
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
            job.error = ""
            job.completed_at = 0.0
        job.save_to_disk()
        self._push_sse(job_id, job)

        proc = _mp_ctx.Process(
            target=run_job_process,
            args=(
                job.id,
                job.input_epub_path,
                job.output_epub_path,
                job.config,
                job.cancel_event,
                self._mp_queue,
            ),
            daemon=True
        )
        with self._lock:
            self._active_processes[job_id] = proc
        proc.start()

    def _scan_cli_jobs(self) -> list[Job]:
        """Scan the cache directory for progress.json files and verify active CLI processes."""
        cli_jobs = []
        cache_root = Path.home() / ".epuboverlay" / "cache"
        if not cache_root.exists():
            return cli_jobs

        try:
            for cache_dir in cache_root.iterdir():
                if not cache_dir.is_dir():
                    continue
                progress_json = cache_dir / "progress.json"
                if not progress_json.exists():
                    continue
                try:
                    with open(progress_json, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    pid = data.get("pid")
                    if pid is None:
                        continue

                    is_running = False
                    try:
                        proc = psutil.Process(pid)
                        cmdline = proc.cmdline()
                        for arg in cmdline:
                            if 'epuboverlay' in arg and 'epuboverlay-web' not in arg:
                                is_running = True
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    if is_running:
                        job_id = f"cli-{pid}"
                        input_epub_path = Path(data.get("input_epub_path", ""))
                        output_epub_path = Path(data.get("output_epub_path", ""))
                        original_filename = input_epub_path.name

                        total_chars = data.get("total_characters", 0)
                        est_hours = data.get("estimated_total_hours", 0.0)
                        audiobook_dur = data.get("audiobook_duration_seconds", 0.0)

                        if total_chars == 0 and input_epub_path.exists():
                            total_chars, est_hours = estimate_epub_audiobook_duration(
                                input_epub_path, 1.0
                            )

                        job = Job(
                            id=job_id,
                            input_epub_path=input_epub_path,
                            output_epub_path=output_epub_path,
                            original_filename=original_filename,
                            book_title=data.get("book_title", original_filename),
                            status=JobStatus.RUNNING,
                            config={"is_cli": True, "pid": pid},
                            created_at=data.get("updated_at", time.time()),
                            started_at=data.get("updated_at", time.time()),
                            total_characters=total_chars,
                            estimated_total_hours=est_hours,
                            audiobook_duration_seconds=audiobook_dur,
                        )
                        job.current_phase = data.get("phase", "")
                        job.chapter_index = data.get("chapter_index", 0)
                        job.chapter_total = data.get("chapter_total", 0)
                        job.chapter_name = data.get("chapter_name", "")
                        job.chunk_index = data.get("chunk_index", 0)
                        job.chunk_total = data.get("chunk_total", 0)
                        job.elapsed_seconds = data.get("elapsed_seconds", 0.0)
                        job.message = data.get("message", "")
                        job.overall_percent = data.get("overall_percent", 0.0)
                        job.total_chunks_to_synthesize = data.get("total_chunks_to_synthesize", 0)
                        job.chunks_processed_so_far = data.get("chunks_processed_so_far", 0)
                        job.synthesis_elapsed_seconds = data.get("synthesis_elapsed_seconds", 0.0)

                        cli_jobs.append(job)
                except Exception as e:
                    print(f"Error reading progress file {progress_json}: {e}")
        except Exception as e:
            print(f"Error scanning cache root {cache_root}: {e}")

        return cli_jobs

    def cancel_job(self, job_id: str) -> bool:
        """Signal a running job to cancel."""
        if job_id.startswith("cli-"):
            try:
                pid = int(job_id.split("-")[1])
                os.kill(pid, signal.SIGTERM)
                return True
            except Exception as e:
                print(f"Failed to kill CLI process {pid}: {e}")
                return False

        job = self.get_job(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return False

        job.cancel_event.set()

        with self._lock:
            job.status = JobStatus.CANCELLED
            job.error = "Cancelled by user."
            job.completed_at = time.time()
        job.save_to_disk()
        self._push_sse(job_id, job)

        proc = self._active_processes.get(job_id)
        if proc and proc.is_alive():
            def _terminator():
                proc.join(timeout=5.0)
                if proc.is_alive():
                    print(f"Process for job {job_id} did not exit cleanly. Terminating...")
                    proc.terminate()
                    proc.join(timeout=3.0)
                    if proc.is_alive():
                        print(f"Process for job {job_id} still alive. Killing...")
                        proc.kill()
                        proc.join()
                with self._lock:
                    self._active_processes.pop(job_id, None)
            
            threading.Thread(target=_terminator, daemon=True).start()
        else:
            with self._lock:
                self._active_processes.pop(job_id, None)

        return True

    def get_job(self, job_id: str) -> Job | None:
        if job_id.startswith("cli-"):
            cli_jobs = self._scan_cli_jobs()
            for job in cli_jobs:
                if job.id == job_id:
                    return job
            return None

        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            jobs = list(reversed(self._jobs.values()))
        cli_jobs = self._scan_cli_jobs()
        return cli_jobs + jobs

    def get_chapter_audio_path(self, job_id: str, chapter_idref: str) -> Path | None:
        """Get the MP3 file path for a completed chapter."""
        job = self.get_job(job_id)
        if job is None:
            return None
        for ca in job.chapter_audios:
            if ca.idref == chapter_idref and ca.mp3_path.exists():
                return ca.mp3_path
        return None

    def update_job_progress(self, job_id: str, event: Any) -> None:
        """Update job progress from a ProgressEvent and notify SSE subscribers."""
        job = self.get_job(job_id)
        if job is None:
            return

        job.current_phase = event.phase
        job.chapter_index = event.chapter_index
        job.chapter_total = event.chapter_total
        job.chapter_name = event.chapter_name
        job.chunk_index = event.chunk_index
        job.chunk_total = event.chunk_total
        job.elapsed_seconds = event.elapsed_seconds
        job.message = event.message
        job.overall_percent = event.overall_percent

        self._push_sse(job_id, job)

    def add_chapter_audio(self, job_id: str, idref: str, mp3_path: Path) -> None:
        """Record a completed chapter audio and copy to the job's audio dir."""
        job = self.get_job(job_id)
        if job is None:
            return

        # Copy MP3 to permanent job audio directory
        dest = self._data_dir / job_id / "audio" / f"{idref}.mp3"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mp3_path, dest)

        ca = ChapterAudio(idref=idref, mp3_path=dest, completed_at=time.time())
        job.chapter_audios.append(ca)
        job.save_to_disk()
        self._push_sse(job_id, job)

    # --- SSE (Server-Sent Events) support ---

    def subscribe_sse(self, job_id: str) -> Queue:
        """Create a new SSE subscription queue for a job."""
        q: Queue = Queue()
        with self._lock:
            if job_id not in self._sse_queues:
                self._sse_queues[job_id] = []
            self._sse_queues[job_id].append(q)
        return q

    def unsubscribe_sse(self, job_id: str, q: Queue) -> None:
        """Remove an SSE subscription queue."""
        with self._lock:
            if job_id in self._sse_queues:
                try:
                    self._sse_queues[job_id].remove(q)
                except ValueError:
                    pass

    def _push_sse(self, job_id: str, job: Job) -> None:
        """Push a job state update to all SSE subscribers."""
        with self._lock:
            queues = list(self._sse_queues.get(job_id, []))
        data = job.to_dict()
        for q in queues:
            try:
                q.put_nowait(data)
            except Exception:
                pass
