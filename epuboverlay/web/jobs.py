"""Job manager for epuboverlay web dashboard — single-job, thread-safe."""
from __future__ import annotations

import shutil
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

        return job

    def start_job(self, job_id: str, run_fn: Callable[[Job], None]) -> None:
        """Start a job in a background thread."""
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        def _worker():
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
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
                self._push_sse(job_id, job)

        thread = threading.Thread(target=_worker, daemon=True)
        self._current_thread = thread
        thread.start()

    def cancel_job(self, job_id: str) -> bool:
        """Signal a running job to cancel."""
        job = self.get_job(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return False
        job.cancel_event.set()
        return True

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(reversed(self._jobs.values()))

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
