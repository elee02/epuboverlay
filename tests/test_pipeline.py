import io
import sys
import tempfile
import unittest
import wave
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from epuboverlay.pipeline import (
    TextChunk,
    TimestampedLine,
    DummySynthesizer,
    extract_spine_text_chunks,
    format_lrc,
    synthesize_with_internal_timestamps,
    replace_html_entities,
    split_into_sentences,
    chunk_text,
    generate_smil_content,
    concatenate_wavs,
    generate_media_overlay_epub,
)


class DummyFrameSynthesizer:
    def __init__(self, frame_counts: list[int]) -> None:
        self._frame_counts = frame_counts
        self._index = 0

    def synthesize(self, text: str) -> tuple[bytes, int]:
        count = self._frame_counts[self._index]
        self._index += 1
        return text.encode("utf-8"), count


class PipelineTests(unittest.TestCase):
    def test_internal_timestamps_are_accumulated_from_frames(self) -> None:
        chunks = [TextChunk("Hello"), TextChunk("World")]
        synth = DummyFrameSynthesizer([100, 50])

        audio_chunks, lines = synthesize_with_internal_timestamps(
            chunks, synth, frame_rate_hz=100
        )

        self.assertEqual(audio_chunks, [b"Hello", b"World"])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(lines[0].start_seconds, 0.0)
        self.assertAlmostEqual(lines[1].start_seconds, 1.0)

    def test_format_lrc_uses_minutes_seconds_hundredths(self) -> None:
        content = format_lrc(
            [
                TimestampedLine(start_seconds=0.0, text="start"),
                TimestampedLine(start_seconds=61.237, text="later"),
            ]
        )
        self.assertEqual(content.splitlines(), ["[00:00.00] start", "[01:01.24] later"])

    def test_extract_spine_text_chunks_reads_ordered_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            epub_path = Path(tmpdir) / "sample.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                        <item id='c2' href='chapter2.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                        <itemref idref='c2'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><h1>One</h1><p>First chapter.</p></body></html>",
                )
                zf.writestr(
                    "OEBPS/chapter2.xhtml",
                    "<html><body><h1>Two</h1><p>Second chapter.</p></body></html>",
                )

            chunks = extract_spine_text_chunks(epub_path)
            self.assertEqual([c.text for c in chunks], ["One First chapter.", "Two Second chapter."])

    def test_replace_html_entities(self) -> None:
        self.assertEqual(
            replace_html_entities("Hello &nbsp; world &ldquo; test &rdquo; &amp; &lt;"),
            "Hello &#160; world &#8220; test &#8221; &amp; &lt;"
        )

    def test_split_into_sentences(self) -> None:
        text = "Mr. Smith went to the store. He bought milk. Dr. Jones was there, too!"
        sentences = split_into_sentences(text)
        self.assertEqual(
            sentences,
            [
                "Mr. Smith went to the store.",
                "He bought milk.",
                "Dr. Jones was there, too!"
            ]
        )

    def test_chunk_text(self) -> None:
        text = "This is a sentence. And this is a very long sentence that has some clauses, which will split it, and more words."
        chunks = chunk_text(text, max_chars=40)
        # Ensure none of the chunks exceed 40 characters
        for c in chunks:
            self.assertTrue(len(c) <= 40, f"Chunk too long: {c}")

    def test_generate_smil_content(self) -> None:
        mappings = [
            ("s1", 0.0, 1.5),
            ("s2", 1.5, 3.75)
        ]
        smil = generate_smil_content("chapter1.xhtml", mappings, "audio/chapter1.mp3")
        self.assertIn('<text src="chapter1.xhtml#s1"/>', smil)
        self.assertIn('<audio src="audio/chapter1.mp3" clipBegin="1.500s" clipEnd="3.750s"/>', smil)

    def test_concatenate_wavs(self) -> None:
        out1 = io.BytesIO()
        with wave.open(out1, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00" * 100)
        wav1 = out1.getvalue()

        out2 = io.BytesIO()
        with wave.open(out2, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x11" * 100)
        wav2 = out2.getvalue()

        merged = concatenate_wavs([wav1, wav2])
        merged_io = io.BytesIO(merged)
        with wave.open(merged_io, "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), 8000)
            self.assertEqual(w.getnframes(), 100)

    def test_generate_media_overlay_epub(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_epub = Path(tmpdir) / "sample.epub"
            output_epub = Path(tmpdir) / "synced.epub"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr(
                    "mimetype",
                    "application/epub+zip",
                )
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Test Book</dc:title>
                      </metadata>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello world. This is a synced book test.</p></body></html>",
                )

            synth = DummySynthesizer(sample_rate=8000)
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
            )

            self.assertTrue(output_epub.exists())

            with zipfile.ZipFile(output_epub, "r") as zf:
                files = zf.namelist()
                self.assertIn("OEBPS/chapter1.xhtml", files)
                self.assertIn("OEBPS/smil_c1.smil", files)
                self.assertIn("OEBPS/audio/audio_c1.mp3", files)

                opf_data = zf.read("OEBPS/content.opf")
                opf_root = ET.fromstring(opf_data)

                manifest = opf_root.find(".//{*}manifest")
                items = manifest.findall(".//{*}item")
                media_overlays = [i.attrib.get("media-overlay") for i in items if i.attrib.get("id") == "c1"]
                self.assertEqual(media_overlays, ["smil_c1"])

                metadata = opf_root.find(".//{*}metadata")
                metas = metadata.findall(".//{*}meta")
                durations = [m.text for m in metas if m.attrib.get("property") == "media:duration"]
                self.assertEqual(len(durations), 2)
                refined_durations = [m.text for m in metas if m.attrib.get("refines") == "#smil_c1"]
                self.assertEqual(len(refined_durations), 1)

    def test_progress_events_are_emitted(self) -> None:
        from epuboverlay.progress import ProgressEvent

        with tempfile.TemporaryDirectory() as tmpdir:
            input_epub = Path(tmpdir) / "sample.epub"
            output_epub = Path(tmpdir) / "synced.epub"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Test Book</dc:title>
                      </metadata>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello world.</p></body></html>",
                )

            events = []
            def progress_cb(event: ProgressEvent):
                events.append(event)

            synth = DummySynthesizer(sample_rate=8000)
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
                progress_callback=progress_cb,
            )

            self.assertTrue(len(events) > 0)
            phases = [e.phase for e in events]
            self.assertIn("parsing", phases)
            self.assertIn("synthesizing", phases)
            self.assertIn("converting", phases)
            self.assertIn("packaging", phases)
            self.assertIn("done", phases)

    def test_checkpointing_resumes_and_skips_processing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_epub = Path(tmpdir) / "sample.epub"
            output_epub1 = Path(tmpdir) / "synced1.epub"
            output_epub2 = Path(tmpdir) / "synced2.epub"
            cache_dir = Path(tmpdir) / "cache"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles>
                        <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
                      </rootfiles>
                    </container>
                    """,
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                        <dc:title>Test Book</dc:title>
                      </metadata>
                      <manifest>
                        <item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/>
                        <item id='c2' href='chapter2.xhtml' media-type='application/xhtml+xml'/>
                      </manifest>
                      <spine>
                        <itemref idref='c1'/>
                        <itemref idref='c2'/>
                      </spine>
                    </package>
                    """,
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello chapter one.</p></body></html>",
                )
                zf.writestr(
                    "OEBPS/chapter2.xhtml",
                    "<html><body><p>Hello chapter two.</p></body></html>",
                )

            # First run: run with a tracking synthesizer to verify it gets called
            class TrackingSynthesizer:
                def __init__(self):
                    self.synthesize_calls = []
                def synthesize(self, text: str) -> tuple[bytes, int]:
                    self.synthesize_calls.append(text)
                    # Return mock WAV (silence)
                    out_io = io.BytesIO()
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(1)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(8000)
                        wav_out.writeframes(b"\x00" * 1600)  # 0.2 seconds
                    return out_io.getvalue(), 1600

            synth1 = TrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub1,
                synthesizer=synth1,
                frame_rate_hz=8000.0,
                cache_dir=cache_dir,
            )

            # Verify both chapters were synthesized
            self.assertEqual(len(synth1.synthesize_calls), 2)
            self.assertIn("Hello chapter one.", synth1.synthesize_calls)
            self.assertIn("Hello chapter two.", synth1.synthesize_calls)

            # Second run: run with same cache dir but a new tracking synthesizer
            synth2 = TrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub2,
                synthesizer=synth2,
                frame_rate_hz=8000.0,
                cache_dir=cache_dir,
            )

            # Verify synthesizer was NOT called because they are cached
            self.assertEqual(len(synth2.synthesize_calls), 0)
            self.assertTrue(output_epub2.exists())

    def test_job_serialization_and_deserialization(self) -> None:
        from epuboverlay.web.jobs import Job, JobStatus, ChapterAudio
        import time

        job = Job(
            id="test-job",
            input_epub_path=Path("/tmp/input.epub"),
            output_epub_path=Path("/tmp/output.epub"),
            original_filename="book.epub",
            book_title="Test Title",
            status=JobStatus.RUNNING,
            config={"synthesizer": "dummy"},
            created_at=time.time(),
            started_at=time.time(),
            completed_at=0.0,
            error="",
        )
        job.current_phase = "synthesizing"
        job.chapter_index = 1
        job.chapter_total = 10
        job.chapter_name = "c1"
        job.chunk_index = 2
        job.chunk_total = 5
        job.elapsed_seconds = 12.34
        job.overall_percent = 25.5

        job.chapter_audios = [
            ChapterAudio(idref="c1", mp3_path=Path("/tmp/audio/c1.mp3"), completed_at=time.time())
        ]

        data = job.to_serialize_dict()
        self.assertEqual(data["id"], "test-job")
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["progress"]["phase"], "synthesizing")
        self.assertEqual(len(data["chapter_audios"]), 1)

        restored = Job.from_dict(data)
        self.assertEqual(restored.id, "test-job")
        self.assertEqual(restored.status, JobStatus.RUNNING)
        self.assertEqual(restored.input_epub_path, Path("/tmp/input.epub"))
        self.assertEqual(restored.current_phase, "synthesizing")
        self.assertEqual(restored.overall_percent, 25.5)
        self.assertEqual(len(restored.chapter_audios), 1)
        self.assertEqual(restored.chapter_audios[0].idref, "c1")
        self.assertEqual(restored.chapter_audios[0].mp3_path, Path("/tmp/audio/c1.mp3"))

    def test_job_manager_persistence(self) -> None:
        from epuboverlay.web.jobs import JobManager, JobStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "jobs"

            # Create dummy input epub file for creation check
            input_epub = Path(tmpdir) / "dummy.epub"
            with open(input_epub, "wb") as f:
                f.write(b"PKmockepub")

            # 1. Initialize JobManager, create a job
            jm1 = JobManager(data_dir=data_dir)
            job = jm1.create_job(
                input_epub_path=input_epub,
                original_filename="dummy.epub",
                config={"synthesizer": "dummy"},
            )
            job_id = job.id

            # Verify job directory and job.json exist
            job_json = data_dir / job_id / "job.json"
            self.assertTrue(job_json.exists())

            # Change status to running and save
            job.status = JobStatus.RUNNING
            job.save_to_disk()

            # 2. Initialize new JobManager to simulate server restart
            jm2 = JobManager(data_dir=data_dir)
            loaded_job = jm2.get_job(job_id)
            self.assertIsNotNone(loaded_job)
            self.assertEqual(loaded_job.original_filename, "dummy.epub")
            
            # Verify status correction: RUNNING should have transitioned to FAILED with server restarted error
            self.assertEqual(loaded_job.status, JobStatus.FAILED)
            self.assertIn("Server restarted", loaded_job.error)

    def test_web_api_job_persistence(self) -> None:
        from fastapi.testclient import TestClient
        from epuboverlay.web.server import app
        from epuboverlay.web.jobs import JobManager
        import epuboverlay.web.server as server_mod
        import shutil

        tmpdir = tempfile.mkdtemp()
        temp_jobs_dir = Path(tmpdir) / "jobs"
        temp_jobs_dir.mkdir()

        original_jm = server_mod.job_manager

        try:
            server_mod.job_manager = JobManager(data_dir=temp_jobs_dir)
            client = TestClient(app)

            # Check empty list
            response = client.get("/api/jobs")
            self.assertEqual(response.status_code, 200)
            jobs_list_initial = [j for j in response.json() if not j["id"].startswith("cli-")]
            self.assertEqual(jobs_list_initial, [])

            # Create a job using upload epub
            dummy_epub = Path(tmpdir) / "dummy.epub"
            with zipfile.ZipFile(dummy_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0'><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test Web Persist</dc:title></metadata><manifest></manifest><spine></spine></package>""",
                )

            with open(dummy_epub, "rb") as f:
                response = client.post(
                    "/api/jobs",
                    files={"epub": ("dummy.epub", f, "application/epub+zip")},
                    data={
                        "synthesizer": "dummy",
                        "speed": 1.0,
                        "max_chars": 150,
                        "frame_rate": 24000.0,
                    }
                )
            self.assertEqual(response.status_code, 200)
            job_data = response.json()
            job_id = job_data["id"]
            self.assertEqual(job_data["book_title"], "Test Web Persist")

            # Verify job.json is on disk
            self.assertTrue((temp_jobs_dir / job_id / "job.json").exists())

            # Cancel the active job so the background pipeline thread terminates
            client.post(f"/api/jobs/{job_id}/cancel")
            import time
            time.sleep(0.05)

            # Re-initialize the job manager to simulate server restart
            server_mod.job_manager = JobManager(data_dir=temp_jobs_dir)

            # List again, verify the job is restored!
            response = client.get("/api/jobs")
            self.assertEqual(response.status_code, 200)
            jobs_list = [j for j in response.json() if not j["id"].startswith("cli-")]
            self.assertEqual(len(jobs_list), 1)
            self.assertEqual(jobs_list[0]["id"], job_id)
            self.assertEqual(jobs_list[0]["book_title"], "Test Web Persist")

        finally:
            server_mod.job_manager = original_jm
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cli_process_discovery_and_cancellation(self) -> None:
        import subprocess
        import time
        import os
        import json
        from epuboverlay.web.jobs import JobManager, JobStatus

        process = subprocess.Popen([
            sys.executable,
            "-c",
            "import time; time.sleep(10)",
            "--dummy-arg-epuboverlay-test"
        ])
        pid = process.pid

        cache_dir = Path.home() / ".epuboverlay" / "cache" / f"test_cli_{pid}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        progress_json = cache_dir / "progress.json"

        try:
            progress_data = {
                "pid": pid,
                "input_epub_path": "/tmp/mock_book.epub",
                "output_epub_path": "/tmp/mock_book_synced.epub",
                "book_title": "CLI Test Book Title",
                "phase": "synthesizing",
                "chapter_index": 3,
                "chapter_total": 8,
                "overall_percent": 37.5,
                "updated_at": time.time(),
            }
            with open(progress_json, "w", encoding="utf-8") as f:
                json.dump(progress_data, f, indent=2)

            jm = JobManager()
            cli_jobs = jm._scan_cli_jobs()

            discovered_jobs = [j for j in cli_jobs if j.id == f"cli-{pid}"]
            self.assertEqual(len(discovered_jobs), 1)
            discovered_job = discovered_jobs[0]
            self.assertEqual(discovered_job.book_title, "CLI Test Book Title")
            self.assertEqual(discovered_job.status, JobStatus.RUNNING)
            self.assertEqual(discovered_job.current_phase, "synthesizing")
            self.assertEqual(discovered_job.overall_percent, 37.5)

            result = jm.cancel_job(f"cli-{pid}")
            self.assertTrue(result)

            process.wait(timeout=2.0)
            self.assertIsNotNone(process.returncode)

        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
            if progress_json.exists():
                progress_json.unlink()
            if cache_dir.exists():
                cache_dir.rmdir()

    def test_web_api_system_stats(self) -> None:
        from fastapi.testclient import TestClient
        from epuboverlay.web.server import app

        client = TestClient(app)
        response = client.get("/api/stats")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("cpu_percent", data)
        self.assertIn("ram_percent", data)
        self.assertIn("disk_percent", data)
        self.assertIn("ram_used_gb", data)
        self.assertIn("ram_total_gb", data)
        self.assertIn("disk_used_gb", data)
        self.assertIn("disk_total_gb", data)

        if data["gpu"] is not None:
            gpu_data = data["gpu"]
            self.assertIn("name", gpu_data)
            self.assertIn("vram_used", gpu_data)
            self.assertIn("vram_total", gpu_data)
            self.assertIn("utilization", gpu_data)
            self.assertIn("temperature", gpu_data)

    def test_generate_media_overlay_epub_parallel(self) -> None:
        import io
        import wave
        import zipfile
        import threading
        from pathlib import Path
        import tempfile
        import shutil

        # Create temporary directory
        tmpdir = tempfile.mkdtemp()
        try:
            input_epub = Path(tmpdir) / "input.epub"
            output_epub = Path(tmpdir) / "output.epub"

            # Create a simple mock EPUB
            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0'><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Parallel Test</dc:title></metadata><manifest><item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chap1"/></spine></package>""",
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello chunk one. Hello chunk two. Hello chunk three. Hello chunk four.</p></body></html>",
                )

            class ThreadSafeTrackingSynthesizer:
                def __init__(self):
                    self.synthesize_calls = []
                    self.lock = threading.Lock()

                def synthesize(self, text: str) -> tuple[bytes, int]:
                    with self.lock:
                        self.synthesize_calls.append(text)
                    # Return mock WAV (silence)
                    out_io = io.BytesIO()
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(1)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(8000)
                        wav_out.writeframes(b"\x00" * 1600)  # 0.2 seconds
                    return out_io.getvalue(), 1600

            synth = ThreadSafeTrackingSynthesizer()
            # Generate with concurrency = 3
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
                max_chars=30,  # make max_chars small to force splitting into multiple chunks
                concurrency=3,
            )

            self.assertTrue(output_epub.exists())
            # Verify we generated multiple chunks and all of them were synthesized
            self.assertEqual(len(synth.synthesize_calls), 4)
            self.assertIn("Hello chunk one.", synth.synthesize_calls)
            self.assertIn("Hello chunk two.", synth.synthesize_calls)
            self.assertIn("Hello chunk three.", synth.synthesize_calls)
            self.assertIn("Hello chunk four.", synth.synthesize_calls)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chunk_level_resumption_sequential(self) -> None:
        from pathlib import Path
        import tempfile
        import shutil
        import hashlib
        import io

        tmpdir = tempfile.mkdtemp()
        try:
            input_epub = Path(tmpdir) / "input.epub"
            output_epub = Path(tmpdir) / "output.epub"
            cache_dir = Path(tmpdir) / "cache"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0'><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Resumption Test</dc:title></metadata><manifest><item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chap1"/></spine></package>""",
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello chunk one. Hello chunk two. Hello chunk three. Hello chunk four.</p></body></html>",
                )

            # Pre-populate cache directory with EPUB extraction and marker file
            cache_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(input_epub, "r") as zf:
                zf.extractall(cache_dir)
            from epuboverlay.pipeline import compute_file_md5
            epub_hash = compute_file_md5(input_epub)
            (cache_dir / ".extracted").write_text(epub_hash)

            # Now pre-populate chunks 0 and 1
            chunks_dir = cache_dir / "_chunks_chap1"
            chunks_dir.mkdir(parents=True, exist_ok=True)

            out_io = io.BytesIO()
            with wave.open(out_io, "wb") as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(8000)
                wav_out.writeframes(b"\x00" * 1600)  # 1600 frames (0.2 seconds)
            wav_bytes = out_io.getvalue()

            hash1 = hashlib.md5(b"Hello chunk one.").hexdigest()[:16]
            hash2 = hashlib.md5(b"Hello chunk two.").hexdigest()[:16]

            (chunks_dir / f"chunk_000000_{hash1}.wav").write_bytes(wav_bytes)
            (chunks_dir / f"chunk_000001_{hash2}.wav").write_bytes(wav_bytes)

            class TrackingSynthesizer:
                def __init__(self):
                    self.synthesize_calls = []
                def synthesize(self, text: str) -> tuple[bytes, int]:
                    self.synthesize_calls.append(text)
                    out_io = io.BytesIO()
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(1)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(8000)
                        wav_out.writeframes(b"\x00" * 1600)
                    return out_io.getvalue(), 1600

            synth = TrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
                max_chars=30,
                concurrency=1,
                cache_dir=cache_dir,
            )

            self.assertTrue(output_epub.exists())
            # Verify only chunk 3 and 4 were synthesized
            self.assertEqual(len(synth.synthesize_calls), 2)
            self.assertIn("Hello chunk three.", synth.synthesize_calls)
            self.assertIn("Hello chunk four.", synth.synthesize_calls)
            # Verify temp chunks dir was cleaned up
            self.assertFalse(chunks_dir.exists())

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chunk_level_resumption_concurrent(self) -> None:
        from pathlib import Path
        import tempfile
        import shutil
        import hashlib
        import io
        import threading

        tmpdir = tempfile.mkdtemp()
        try:
            input_epub = Path(tmpdir) / "input.epub"
            output_epub = Path(tmpdir) / "output.epub"
            cache_dir = Path(tmpdir) / "cache"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0'><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Concurrent Resumption Test</dc:title></metadata><manifest><item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chap1"/></spine></package>""",
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello chunk one. Hello chunk two. Hello chunk three. Hello chunk four.</p></body></html>",
                )

            # Pre-populate cache directory with EPUB extraction and marker file
            cache_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(input_epub, "r") as zf:
                zf.extractall(cache_dir)
            from epuboverlay.pipeline import compute_file_md5
            epub_hash = compute_file_md5(input_epub)
            (cache_dir / ".extracted").write_text(epub_hash)

            # Now pre-populate chunks 0 and 1
            chunks_dir = cache_dir / "_chunks_chap1"
            chunks_dir.mkdir(parents=True, exist_ok=True)

            out_io = io.BytesIO()
            with wave.open(out_io, "wb") as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(8000)
                wav_out.writeframes(b"\x00" * 1600)
            wav_bytes = out_io.getvalue()

            hash1 = hashlib.md5(b"Hello chunk one.").hexdigest()[:16]
            hash2 = hashlib.md5(b"Hello chunk two.").hexdigest()[:16]

            (chunks_dir / f"chunk_000000_{hash1}.wav").write_bytes(wav_bytes)
            (chunks_dir / f"chunk_000001_{hash2}.wav").write_bytes(wav_bytes)

            class ThreadSafeTrackingSynthesizer:
                def __init__(self):
                    self.synthesize_calls = []
                    self.lock = threading.Lock()
                def synthesize(self, text: str) -> tuple[bytes, int]:
                    with self.lock:
                        self.synthesize_calls.append(text)
                    out_io = io.BytesIO()
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(1)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(8000)
                        wav_out.writeframes(b"\x00" * 1600)
                    return out_io.getvalue(), 1600

            synth = ThreadSafeTrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
                max_chars=30,
                concurrency=2,
                cache_dir=cache_dir,
            )

            self.assertTrue(output_epub.exists())
            # Verify only chunk 3 and 4 were synthesized
            self.assertEqual(len(synth.synthesize_calls), 2)
            self.assertIn("Hello chunk three.", synth.synthesize_calls)
            self.assertIn("Hello chunk four.", synth.synthesize_calls)
            # Verify temp chunks dir was cleaned up
            self.assertFalse(chunks_dir.exists())

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chunk_level_resumption_corrupt(self) -> None:
        from pathlib import Path
        import tempfile
        import shutil
        import hashlib
        import io

        tmpdir = tempfile.mkdtemp()
        try:
            input_epub = Path(tmpdir) / "input.epub"
            output_epub = Path(tmpdir) / "output.epub"
            cache_dir = Path(tmpdir) / "cache"

            with zipfile.ZipFile(input_epub, "w") as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0'><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Corrupt Cache Test</dc:title></metadata><manifest><item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chap1"/></spine></package>""",
                )
                zf.writestr(
                    "OEBPS/chapter1.xhtml",
                    "<html><body><p>Hello chunk one. Hello chunk two.</p></body></html>",
                )

            # Pre-populate cache directory with EPUB extraction and marker file
            cache_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(input_epub, "r") as zf:
                zf.extractall(cache_dir)
            from epuboverlay.pipeline import compute_file_md5
            epub_hash = compute_file_md5(input_epub)
            (cache_dir / ".extracted").write_text(epub_hash)

            # Now pre-populate chunks (chunk 0 valid, chunk 1 corrupt)
            chunks_dir = cache_dir / "_chunks_chap1"
            chunks_dir.mkdir(parents=True, exist_ok=True)

            out_io = io.BytesIO()
            with wave.open(out_io, "wb") as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(8000)
                wav_out.writeframes(b"\x00" * 1600)
            wav_bytes = out_io.getvalue()

            hash1 = hashlib.md5(b"Hello chunk one.").hexdigest()[:16]
            hash2 = hashlib.md5(b"Hello chunk two.").hexdigest()[:16]

            (chunks_dir / f"chunk_000000_{hash1}.wav").write_bytes(wav_bytes)
            # Write invalid/corrupt content
            (chunks_dir / f"chunk_000001_{hash2}.wav").write_bytes(b"corrupted contents")

            class TrackingSynthesizer:
                def __init__(self):
                    self.synthesize_calls = []
                def synthesize(self, text: str) -> tuple[bytes, int]:
                    self.synthesize_calls.append(text)
                    out_io = io.BytesIO()
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(1)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(8000)
                        wav_out.writeframes(b"\x00" * 1600)
                    return out_io.getvalue(), 1600

            synth = TrackingSynthesizer()
            generate_media_overlay_epub(
                input_epub=input_epub,
                output_epub=output_epub,
                synthesizer=synth,
                frame_rate_hz=8000.0,
                max_chars=30,
                concurrency=1,
                cache_dir=cache_dir,
            )

            self.assertTrue(output_epub.exists())
            # Verify only chunk 1 was synthesized (chunk 0 was reused, chunk 1 was re-synthesized because it was corrupt)
            self.assertEqual(len(synth.synthesize_calls), 1)
            self.assertIn("Hello chunk two.", synth.synthesize_calls)
            self.assertFalse(chunks_dir.exists())

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(unittest.main())
