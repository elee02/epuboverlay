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
    cancel_event: threading.Event = field(default_factory=threading.Event)

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

    @property
    def job_dir(self) -> Path:
        return self.input_epub_path.parent

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
            },
            "chapter_audios": [
                {"idref": ca.idref, "completed_at": ca.completed_at}
                for ca in self.chapter_audios
            ],
        }


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


class JobManager:
    """Manages job lifecycle — single-job at a time."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or Path.home() / ".epuboverlay" / "jobs"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._current_thread: threading.Thread | None = None
        self._sse_queues: dict[str, list[Queue]] = {}  # job_id -> list of subscriber queues
        self._load_jobs_from_disk()

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

        output_epub = job_dir / f"output_{original_filename}"
        audio_dir = job_dir / "audio"
        audio_dir.mkdir(exist_ok=True)

        book_title = extract_epub_title(stored_epub)

        job = Job(
            id=job_id,
            input_epub_path=stored_epub,
            output_epub_path=output_epub,
            original_filename=original_filename,
            book_title=book_title,
            config=config,
        )

        with self._lock:
            self._jobs[job_id] = job
            self._sse_queues[job_id] = []

        job.save_to_disk()
        return job

    def start_job(self, job_id: str, run_fn: Callable[[Job], None]) -> None:
        """Start a job in a background thread."""
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        def _worker():
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
            job.save_to_disk()
            self._push_sse(job_id, job)
            try:
                run_fn(job)
                if job.status == JobStatus.RUNNING:
                    job.status = JobStatus.COMPLETED
                    job.completed_at = time.time()
            except Exception as e:
                if job.cancel_event.is_set():
                    job.status = JobStatus.CANCELLED
                    job.error = "Cancelled by user."
                else:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                job.completed_at = time.time()
            finally:
                job.save_to_disk()
                self._push_sse(job_id, job)

        thread = threading.Thread(target=_worker, daemon=True)
        self._current_thread = thread
        thread.start()

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
