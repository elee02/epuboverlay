/* ═══════════════════════════════════════════════════════════════
   epuboverlay Dashboard — Frontend Application
   SSE progress, file uploads, audio preview, job management
   ═══════════════════════════════════════════════════════════════ */

// ── DOM References ──
const jobForm = document.getElementById('job-form');
const submitBtn = document.getElementById('submit-btn');
const epubFile = document.getElementById('epub-file');
const epubUploadZone = document.getElementById('epub-upload-zone');
const epubFileName = document.getElementById('epub-file-name');
const refAudioFile = document.getElementById('ref-audio-file');
const refAudioUploadZone = document.getElementById('ref-audio-upload-zone');
const refAudioFileName = document.getElementById('ref-audio-file-name');
const refAudioFields = document.getElementById('ref-audio-fields');
const synthSelect = document.getElementById('synthesizer-select');
const activeJobSection = document.getElementById('active-job-section');
const activeJobContainer = document.getElementById('active-job-container');
const completedSection = document.getElementById('completed-section');
const completedContainer = document.getElementById('completed-container');
const completedCount = document.getElementById('completed-count');
const failedSection = document.getElementById('failed-section');
const failedContainer = document.getElementById('failed-container');
const failedCount = document.getElementById('failed-count');
const toastContainer = document.getElementById('toast-container');

// ── State ──
let activeSSE = null;
let jobs = [];

// ── Initialize ──
document.addEventListener('DOMContentLoaded', () => {
    loadJobs();
    setupFileUploads();
    setupSynthesizerToggle();
    setupForm();
    startStatsPolling();
});

// ── Toast Notifications ──
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { success: '✓', error: '✗', info: 'ℹ' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> <span>${message}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

// ── File Upload Handling ──
function setupFileUploads() {
    // EPUB file
    setupDropZone(epubUploadZone, epubFile, epubFileName);
    // Ref audio file
    setupDropZone(refAudioUploadZone, refAudioFile, refAudioFileName);
}

function setupDropZone(zone, input, nameDisplay) {
    ['dragover', 'dragenter'].forEach(evt => {
        zone.addEventListener(evt, (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(evt => {
        zone.addEventListener(evt, () => {
            zone.classList.remove('dragover');
        });
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            input.files = files;
            showFileName(nameDisplay, files[0].name);
        }
    });

    input.addEventListener('change', () => {
        if (input.files.length > 0) {
            showFileName(nameDisplay, input.files[0].name);
        }
    });
}

function showFileName(el, name) {
    el.textContent = `📎 ${name}`;
    el.style.display = 'block';
}

// ── Synthesizer Toggle ──
function setupSynthesizerToggle() {
    synthSelect.addEventListener('change', () => {
        const isF5 = synthSelect.value === 'f5-tts';
        refAudioFields.classList.toggle('hidden', !isF5);
    });
}

// ── Form Submission ──
function setupForm() {
    jobForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(jobForm);

        // Validation
        if (!epubFile.files.length) {
            showToast('Please select an EPUB file.', 'error');
            return;
        }

        if (synthSelect.value === 'f5-tts') {
            if (!refAudioFile.files.length) {
                showToast('Reference audio is required for F5-TTS.', 'error');
                return;
            }
            if (!formData.get('ref_text')?.trim()) {
                showToast('Reference text is required for F5-TTS.', 'error');
                return;
            }
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Submitting...';

        try {
            const resp = await fetch('/api/jobs', {
                method: 'POST',
                body: formData,
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || 'Failed to create job');
            }

            const job = await resp.json();
            showToast('Job submitted successfully!', 'success');
            jobForm.reset();
            epubFileName.style.display = 'none';
            refAudioFileName.style.display = 'none';

            // Show active job and start SSE
            renderActiveJob(job);
            connectSSE(job.id);

        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '🚀 Start Generation';
        }
    });
}

// ── Load Existing Jobs ──
async function loadJobs() {
    try {
        const resp = await fetch('/api/jobs');
        if (!resp.ok) return;
        jobs = await resp.json();

        let hasActive = false;
        const completed = [];
        const failed = [];

        for (const job of jobs) {
            if (job.status === 'running' || job.status === 'queued') {
                renderActiveJob(job);
                connectSSE(job.id);
                hasActive = true;
            } else if (job.status === 'completed') {
                completed.push(job);
            } else {
                failed.push(job);
            }
        }

        renderCompletedJobs(completed);
        renderFailedJobs(failed);

    } catch (err) {
        console.error('Failed to load jobs:', err);
    }
}

// ── SSE Connection ──
function connectSSE(jobId) {
    if (activeSSE) {
        activeSSE.close();
    }

    activeSSE = new EventSource(`/api/jobs/${jobId}/events`);

    activeSSE.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'close') {
            activeSSE.close();
            activeSSE = null;
            return;
        }

        renderActiveJob(data);

        // Handle terminal states
        if (data.status === 'completed') {
            activeSSE.close();
            activeSSE = null;
            showToast('🎉 EPUB generated successfully!', 'success');
            setTimeout(() => {
                moveToCompleted(data);
            }, 1500);
        } else if (data.status === 'failed') {
            activeSSE.close();
            activeSSE = null;
            showToast('Job failed: ' + (data.error || 'Unknown error'), 'error');
            setTimeout(() => {
                moveToFailed(data);
            }, 1500);
        } else if (data.status === 'cancelled') {
            activeSSE.close();
            activeSSE = null;
            showToast('Job cancelled.', 'info');
            setTimeout(() => {
                moveToFailed(data);
            }, 1500);
        }
    };

    activeSSE.onerror = () => {
        // Auto-reconnect after 3 seconds
        setTimeout(() => {
            if (activeSSE && activeSSE.readyState === EventSource.CLOSED) {
                connectSSE(jobId);
            }
        }, 3000);
    };
}

// ── Render Active Job ──
function renderActiveJob(job) {
    activeJobSection.style.display = 'block';

    const progress = job.progress || {};
    const phase = progress.phase || 'initializing';
    const percent = progress.overall_percent || 0;
    const chapterIdx = progress.chapter_index || 0;
    const chapterTotal = progress.chapter_total || 0;
    const chunkIdx = progress.chunk_index || 0;
    const chunkTotal = progress.chunk_total || 0;
    const elapsed = progress.elapsed_seconds || 0;
    const message = progress.message || '';
    const chapterName = progress.chapter_name || '';

    // ETA calculation
    let etaStr = '—';
    if (percent > 0 && percent < 100) {
        const totalEst = elapsed / (percent / 100);
        const remaining = totalEst - elapsed;
        etaStr = formatTime(remaining);
    }

    // Check if card for this job already exists
    let card = activeJobContainer.querySelector(`.card[data-job-id="${job.id}"]`);
    if (!card) {
        // Clear container and create new card structure
        activeJobContainer.innerHTML = `
            <div class="card" data-job-id="${job.id}">
                <div class="card-header">
                    <div class="card-title">
                        <span class="icon">📖</span>
                        <span class="job-book-title">${escapeHtml(job.book_title || job.original_filename)}</span>
                    </div>
                    <span class="phase-badge ${phase}">
                        <span class="pulse-dot"></span>
                        <span class="phase-text">${phase}</span>
                    </span>
                </div>

                <div style="display: flex; align-items: baseline; gap: 1rem; margin-bottom: 0.5rem;">
                    <span class="progress-percent">${percent.toFixed(1)}%</span>
                    <span class="progress-stat progress-chapter-stat">
                        Chapter <strong>${chapterIdx + (phase === 'synthesizing' || phase === 'converting' ? 1 : 0)}/${chapterTotal}</strong>
                    </span>
                    <span class="progress-stat progress-chunk-stat">
                        ${chunkTotal > 0 ? `Chunk <strong>${chunkIdx + 1}/${chunkTotal}</strong>` : ''}
                    </span>
                </div>

                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: ${percent}%"></div>
                </div>

                <div class="progress-stats">
                    <span class="progress-stat progress-elapsed">Elapsed: <strong>${formatTime(elapsed)}</strong></span>
                    <span class="progress-stat progress-eta">ETA: <strong>${etaStr}</strong></span>
                    <span class="progress-stat progress-current-chapter">${chapterName ? `Current: <strong>${escapeHtml(chapterName)}</strong>` : ''}</span>
                </div>

                <div class="synth-preview">${escapeHtml(message)}</div>

                <div class="chapter-audio-list"></div>

                <div class="job-actions">
                    <button class="btn btn-danger btn-sm" onclick="cancelJob('${job.id}')">
                        ✕ Cancel
                    </button>
                </div>
            </div>
        `;
        card = activeJobContainer.querySelector(`.card[data-job-id="${job.id}"]`);
    }

    // Update dynamic properties
    const badge = card.querySelector('.phase-badge');
    if (badge) {
        badge.className = `phase-badge ${phase}`;
        const phaseText = badge.querySelector('.phase-text');
        if (phaseText) phaseText.textContent = phase;
    }

    const percentEl = card.querySelector('.progress-percent');
    if (percentEl) percentEl.textContent = `${percent.toFixed(1)}%`;

    const chapStat = card.querySelector('.progress-chapter-stat strong');
    if (chapStat) {
        chapStat.textContent = `${chapterIdx + (phase === 'synthesizing' || phase === 'converting' ? 1 : 0)}/${chapterTotal}`;
    }

    const chunkStat = card.querySelector('.progress-chunk-stat');
    if (chunkStat) {
        chunkStat.innerHTML = chunkTotal > 0 ? `Chunk <strong>${chunkIdx + 1}/${chunkTotal}</strong>` : '';
    }

    const progressBar = card.querySelector('.progress-bar');
    if (progressBar) progressBar.style.width = `${percent}%`;

    const elapsedEl = card.querySelector('.progress-elapsed strong');
    if (elapsedEl) elapsedEl.textContent = formatTime(elapsed);

    const etaEl = card.querySelector('.progress-eta strong');
    if (etaEl) etaEl.textContent = etaStr;

    const currentChap = card.querySelector('.progress-current-chapter');
    if (currentChap) {
        currentChap.innerHTML = chapterName ? `Current: <strong>${escapeHtml(chapterName)}</strong>` : '';
    }

    const preview = card.querySelector('.synth-preview');
    if (preview) {
        preview.textContent = message;
        preview.style.display = message ? 'block' : 'none';
    }

    // Append new audio elements incrementally without re-rendering existing ones
    const audioList = card.querySelector('.chapter-audio-list');
    if (audioList) {
        const audios = job.chapter_audios || [];
        const rendered = Array.from(audioList.querySelectorAll('.chapter-audio-item')).map(el => el.getAttribute('data-idref'));
        
        audios.forEach(a => {
            if (!rendered.includes(a.idref)) {
                const item = document.createElement('div');
                item.className = 'chapter-audio-item';
                item.setAttribute('data-idref', a.idref);
                item.innerHTML = `
                    <span class="chapter-label">📢 ${escapeHtml(a.idref)}</span>
                    <audio controls preload="none" src="/api/jobs/${job.id}/audio/${encodeURIComponent(a.idref)}"></audio>
                `;
                audioList.appendChild(item);
            }
        });
    }
}

// ── Move Job to Completed ──
function moveToCompleted(job) {
    activeJobSection.style.display = 'none';
    activeJobContainer.innerHTML = '';

    // Re-load all jobs to get the final state
    loadJobs();
}

// ── Move Job to Failed ──
function moveToFailed(job) {
    activeJobSection.style.display = 'none';
    activeJobContainer.innerHTML = '';
    loadJobs();
}

// ── Render Completed Jobs ──
function renderCompletedJobs(completedJobs) {
    if (completedJobs.length === 0) {
        completedSection.style.display = 'none';
        return;
    }

    completedSection.style.display = 'block';
    completedCount.textContent = completedJobs.length;

    completedContainer.innerHTML = completedJobs.map(job => {
        const audios = job.chapter_audios || [];
        const duration = job.completed_at && job.started_at
            ? formatTime(job.completed_at - job.started_at)
            : '—';

        let audioHTML = '';
        if (audios.length > 0) {
            audioHTML = `
                <div class="chapter-audio-list">
                    ${audios.map(a => `
                        <div class="chapter-audio-item">
                            <span class="chapter-label">📢 ${escapeHtml(a.idref)}</span>
                            <audio controls preload="none" src="/api/jobs/${job.id}/audio/${encodeURIComponent(a.idref)}"></audio>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        return `
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="icon">📖</span>
                        ${escapeHtml(job.book_title || job.original_filename)}
                    </div>
                    <span class="status-badge completed">✓ Completed</span>
                </div>

                <div class="progress-stats" style="margin-top: 0;">
                    <span class="progress-stat">Duration: <strong>${duration}</strong></span>
                    <span class="progress-stat">Chapters: <strong>${job.progress?.chapter_total || '—'}</strong></span>
                </div>

                ${audioHTML}

                <div class="job-actions">
                    <a class="btn btn-download btn-sm" href="/api/jobs/${job.id}/download">
                        ⬇ Download EPUB
                    </a>
                </div>
            </div>
        `;
    }).join('');
}

// ── Render Failed Jobs ──
function renderFailedJobs(failedJobs) {
    if (failedJobs.length === 0) {
        failedSection.style.display = 'none';
        return;
    }

    failedSection.style.display = 'block';
    failedCount.textContent = failedJobs.length;

    failedContainer.innerHTML = failedJobs.map(job => `
        <div class="card">
            <div class="card-header">
                <div class="card-title">
                    <span class="icon">📖</span>
                    ${escapeHtml(job.book_title || job.original_filename)}
                </div>
                <span class="status-badge ${job.status}">${job.status === 'cancelled' ? '⊘ Cancelled' : '✗ Failed'}</span>
            </div>

            ${job.error ? `<div class="error-message">${escapeHtml(job.error)}</div>` : ''}
        </div>
    `).join('');
}

// ── Cancel Job ──
async function cancelJob(jobId) {
    try {
        const resp = await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            showToast(err.detail || 'Failed to cancel', 'error');
        } else {
            showToast('Cancellation requested...', 'info');
        }
    } catch (err) {
        showToast('Failed to cancel job.', 'error');
    }
}

// ── Utilities ──
function formatTime(seconds) {
    if (seconds < 0 || isNaN(seconds)) return '—';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    if (m >= 60) {
        const h = Math.floor(m / 60);
        const rm = m % 60;
        return `${h}h ${rm}m`;
    }
    return `${m}m ${s.toFixed(0)}s`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Live System Resource Stats ──
function startStatsPolling() {
    updateStats();
    setInterval(updateStats, 3000);
}

async function updateStats() {
    try {
        const resp = await fetch('/api/stats');
        if (!resp.ok) return;
        const data = await resp.json();

        // CPU
        document.getElementById('stat-cpu').textContent = `${data.cpu_percent.toFixed(0)}%`;
        document.getElementById('fill-cpu').style.width = `${data.cpu_percent}%`;

        // RAM
        document.getElementById('stat-ram').textContent = `${data.ram_used_gb.toFixed(1)} / ${data.ram_total_gb.toFixed(0)} GB`;
        document.getElementById('fill-ram').style.width = `${data.ram_percent}%`;

        // Disk
        document.getElementById('stat-disk').textContent = `${data.disk_used_gb.toFixed(1)} / ${data.disk_total_gb.toFixed(0)} GB`;
        document.getElementById('fill-disk').style.width = `${data.disk_percent}%`;

        // GPU
        const gpuBadge = document.getElementById('gpu-stat-badge');
        if (data.gpu) {
            gpuBadge.style.display = 'flex';
            document.getElementById('gpu-name-label').textContent = data.gpu.name;
            document.getElementById('stat-gpu').textContent = `${data.gpu.utilization.toFixed(0)}% (${data.gpu.vram_used.toFixed(1)} / ${data.gpu.vram_total.toFixed(0)} GB, ${data.gpu.temperature.toFixed(0)}°C)`;
            document.getElementById('fill-gpu').style.width = `${data.gpu.utilization}%`;
        } else {
            gpuBadge.style.display = 'none';
        }
    } catch (err) {
        console.error('Failed to fetch resource stats:', err);
    }
}
