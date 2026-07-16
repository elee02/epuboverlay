import { cancelJob, deleteJob as deleteJobApi, resumeJob as resumeJobApi, fetchJobDetails, loadJobs, convertJobToAudio } from './api.js';
import { showToast, formatTime, escapeHtml } from './utils.js';
import { showConfirmModal } from './modal.js';
import { setupKokoroMixer, updateFilteredVoices, getVoiceMetadata, setVoiceMode, renderBlendMixer } from './kokoro.js';

export let activeSSE = null;

export function connectSSE(jobId, onJobUpdate) {
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

        onJobUpdate(data);

        // Handle terminal states
        if (data.status === 'completed') {
            activeSSE.close();
            activeSSE = null;
            showToast('🎉 EPUB generated successfully!', 'success');
            setTimeout(() => {
                refreshJobsList(onJobUpdate);
            }, 1500);
        } else if (data.status === 'failed') {
            activeSSE.close();
            activeSSE = null;
            showToast('Job failed: ' + (data.error || 'Unknown error'), 'error');
            setTimeout(() => {
                refreshJobsList(onJobUpdate);
            }, 1500);
        } else if (data.status === 'cancelled') {
            activeSSE.close();
            activeSSE = null;
            showToast('Job cancelled.', 'info');
            setTimeout(() => {
                refreshJobsList(onJobUpdate);
            }, 1500);
        }
    };

    activeSSE.onerror = () => {
        setTimeout(() => {
            if (activeSSE && activeSSE.readyState === EventSource.CLOSED) {
                connectSSE(jobId, onJobUpdate);
            }
        }, 3000);
    };
}

export async function refreshJobsList(onJobUpdate) {
    try {
        const jobs = await loadJobs();
        const activeJobSection = document.getElementById('active-job-section');
        const activeJobContainer = document.getElementById('active-job-container');
        const completedSection = document.getElementById('completed-section');
        const failedSection = document.getElementById('failed-section');

        let activeJob = null;
        const completed = [];
        const failed = [];

        for (const job of jobs) {
            if (job.status === 'running' || job.status === 'queued') {
                activeJob = job;
            } else if (job.status === 'completed') {
                completed.push(job);
            } else {
                failed.push(job);
            }
        }

        if (activeJob) {
            renderActiveJob(activeJob, onJobUpdate);
            if (!activeSSE) {
                connectSSE(activeJob.id, onJobUpdate);
            }
        } else {
            if (activeJobSection) activeJobSection.style.display = 'none';
            if (activeJobContainer) activeJobContainer.innerHTML = '';
            if (activeSSE) {
                activeSSE.close();
                activeSSE = null;
            }
        }

        renderCompletedJobs(completed);
        renderFailedJobs(failed, onJobUpdate);

    } catch (err) {
        console.error('Failed to refresh jobs list:', err);
    }
}

export function renderActiveJob(job, onJobUpdate) {
    const activeJobSection = document.getElementById('active-job-section');
    const activeJobContainer = document.getElementById('active-job-container');
    if (!activeJobSection || !activeJobContainer) return;

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

    const chunksProcessed = progress.chunks_processed_so_far || 0;
    const activeChunksProcessed = progress.active_chunks_processed || 0;
    const totalChunksToSynthesize = progress.total_chunks_to_synthesize || 0;
    const synthesisElapsed = progress.synthesis_elapsed_seconds || 0;

    let synthPercent = 0;
    if (totalChunksToSynthesize > 0) {
        synthPercent = Math.min((chunksProcessed / totalChunksToSynthesize) * 100, 100);
    }

    let avgTimePerChunkStr = '—';
    const divisor = activeChunksProcessed > 0 ? activeChunksProcessed : chunksProcessed;
    if (divisor > 0) {
        const avgTime = synthesisElapsed / divisor;
        avgTimePerChunkStr = `${avgTime.toFixed(1)}s`;
    }

    let etaStr = '—';
    if (progress.estimated_remaining_seconds !== undefined && progress.estimated_remaining_seconds !== null) {
        etaStr = formatTime(progress.estimated_remaining_seconds);
    } else if (percent > 0 && percent < 100) {
        const totalEst = elapsed / (percent / 100);
        const remaining = totalEst - elapsed;
        etaStr = formatTime(remaining);
    }

    let estHrsStr = '—';
    if (job.estimated_total_hours) {
        estHrsStr = `~${job.estimated_total_hours.toFixed(1)} hrs`;
        if (job.total_characters) {
            estHrsStr += ` (${(job.total_characters / 1000).toFixed(0)}k chars)`;
        }
    }

    let card = activeJobContainer.querySelector(`.card[data-job-id="${job.id}"]`);
    if (!card) {
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

                <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.25rem;">
                    <span class="progress-label" style="font-size: 0.85rem; font-weight: 500; color: var(--text-secondary);">Overall Book Progress</span>
                    <span class="progress-percent" style="font-size: 0.85rem; font-weight: 600; color: var(--text-primary);">${percent.toFixed(1)}%</span>
                </div>
                <div style="display: flex; align-items: baseline; gap: 1rem; margin-bottom: 0.5rem; font-size: 0.82rem; color: var(--text-secondary);">
                    <span class="progress-chapter-stat">
                        Chapter <strong>${chapterIdx + (phase === 'synthesizing' || phase === 'converting' ? 1 : 0)}/${chapterTotal}</strong>
                    </span>
                    <span class="progress-chunk-stat">
                        ${chunkTotal > 0 ? `Chunk <strong>${chunkIdx + 1}/${chunkTotal}</strong>` : ''}
                    </span>
                </div>
                <div class="progress-bar-container" style="margin-bottom: 1rem;">
                    <div class="progress-bar overall-bar" style="width: ${percent}%"></div>
                </div>

                <div class="synthesis-progress-section" style="display: ${totalChunksToSynthesize > 0 ? 'block' : 'none'};">
                    <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.25rem;">
                        <span class="progress-label" style="font-size: 0.85rem; font-weight: 500; color: var(--text-secondary);">Speech Synthesis Progress</span>
                        <span class="synthesis-percent" style="font-size: 0.85rem; font-weight: 600; color: var(--text-primary);">${synthPercent.toFixed(1)}%</span>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar synthesis-bar" style="width: ${synthPercent}%; background: linear-gradient(135deg, #f43f5e, #fb923c);"></div>
                    </div>
                    <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 1rem; display: flex; justify-content: space-between;">
                        <span>Chunks: <strong class="synthesis-chunks-val">${chunksProcessed}/${totalChunksToSynthesize}</strong></span>
                        <span>Avg. speed: <strong class="synthesis-avg-time-val">${avgTimePerChunkStr} / chunk</strong></span>
                    </div>
                </div>

                <div class="progress-stats">
                    <span class="progress-stat progress-elapsed">Elapsed: <strong>${formatTime(elapsed)}</strong></span>
                    <span class="progress-stat progress-eta">ETA: <strong>${etaStr}</strong></span>
                    <span class="progress-stat progress-audiobook-length">Est. Audiobook: <strong class="job-est-hours">${estHrsStr}</strong></span>
                </div>

                <div class="synth-preview">${escapeHtml(message)}</div>

                <div class="chapter-audio-list"></div>

                <div class="job-actions">
                    <button class="btn btn-danger btn-sm cancel-job-btn">
                        ✕ Cancel
                    </button>
                </div>
            </div>
        `;
        card = activeJobContainer.querySelector(`.card[data-job-id="${job.id}"]`);

        // Bind cancel button
        card.querySelector('.cancel-job-btn').addEventListener('click', async () => {
            try {
                await cancelJob(job.id);
                showToast('Cancellation requested...', 'info');
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    }

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

    const overallBar = card.querySelector('.overall-bar');
    if (overallBar) overallBar.style.width = `${percent}%`;

    const synthSection = card.querySelector('.synthesis-progress-section');
    if (synthSection) {
        if (totalChunksToSynthesize > 0) {
            synthSection.style.display = 'block';
            
            const synthPercentEl = card.querySelector('.synthesis-percent');
            if (synthPercentEl) synthPercentEl.textContent = `${synthPercent.toFixed(1)}%`;
            
            const synthBar = card.querySelector('.synthesis-bar');
            if (synthBar) {
                synthBar.style.width = `${synthPercent}%`;
            }
            
            const chunksVal = card.querySelector('.synthesis-chunks-val');
            if (chunksVal) chunksVal.textContent = `${chunksProcessed}/${totalChunksToSynthesize}`;
            
            const avgTimeVal = card.querySelector('.synthesis-avg-time-val');
            if (avgTimeVal) avgTimeVal.textContent = `${avgTimePerChunkStr} / chunk`;
        } else {
            synthSection.style.display = 'none';
        }
    }

    const elapsedEl = card.querySelector('.progress-elapsed strong');
    if (elapsedEl) elapsedEl.textContent = formatTime(elapsed);

    const etaEl = card.querySelector('.progress-eta strong');
    if (etaEl) etaEl.textContent = etaStr;

    const estHoursEl = card.querySelector('.job-est-hours');
    if (estHoursEl) estHoursEl.textContent = estHrsStr;

    const preview = card.querySelector('.synth-preview');
    if (preview) {
        preview.textContent = message;
        preview.style.display = message ? 'block' : 'none';
    }

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

export function renderCompletedJobs(completedJobs) {
    const completedSection = document.getElementById('completed-section');
    const completedContainer = document.getElementById('completed-container');
    const completedCount = document.getElementById('completed-count');

    if (!completedSection || !completedContainer) return;

    if (completedJobs.length === 0) {
        completedSection.style.display = 'none';
        return;
    }

    completedSection.style.display = 'block';
    if (completedCount) completedCount.textContent = completedJobs.length;

    completedContainer.innerHTML = '';
    completedJobs.forEach(job => {
        const audios = job.chapter_audios || [];
        const duration = job.completed_at && job.started_at
            ? formatTime(job.completed_at - job.started_at)
            : '—';

        const audiobookLength = job.audiobook_duration_seconds 
            ? formatTime(job.audiobook_duration_seconds)
            : (job.estimated_total_hours ? `~${job.estimated_total_hours.toFixed(1)} hrs` : '—');

        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <div class="card-header">
                <div class="card-title">
                    <span class="icon">📖</span>
                    ${escapeHtml(job.book_title || job.original_filename)}
                </div>
                <span class="status-badge completed">✓ Completed</span>
            </div>

            <div class="progress-stats" style="margin-top: 0;">
                <span class="progress-stat">Audiobook Length: <strong>${audiobookLength}</strong></span>
                <span class="progress-stat">Compute Time: <strong>${duration}</strong></span>
                <span class="progress-stat">Chapters: <strong>${job.progress?.chapter_total || '—'}</strong></span>
            </div>

            <div class="chapter-audio-list">
                ${audios.map(a => `
                    <div class="chapter-audio-item">
                        <span class="chapter-label">📢 ${escapeHtml(a.idref)}</span>
                        <audio controls preload="none" src="/api/jobs/${job.id}/audio/${encodeURIComponent(a.idref)}"></audio>
                    </div>
                `).join('')}
            </div>

            <div class="job-actions-row" style="flex-wrap: wrap; gap: 0.75rem 1.5rem;">
                <label class="merge-checkbox-label" for="merge-cb-${job.id}">
                    <input type="checkbox" id="merge-cb-${job.id}" class="merge-chapters-cb">
                    <span>Merge all chapters</span>
                </label>
                <label class="merge-checkbox-label" for="center-cb-${job.id}">
                    <input type="checkbox" id="center-cb-${job.id}" class="center-subtitles-cb">
                    <span>Center subtitles</span>
                </label>
                <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem 1rem;">
                    <span style="font-size: 0.8rem; color: var(--text-secondary); font-weight: 500;">Formats:</span>
                    <label class="merge-checkbox-label" for="fmt-ass-${job.id}">
                        <input type="checkbox" id="fmt-ass-${job.id}" class="fmt-cb-ass" checked>
                        <span>ASS</span>
                    </label>
                    <label class="merge-checkbox-label" for="fmt-srt-${job.id}">
                        <input type="checkbox" id="fmt-srt-${job.id}" class="fmt-cb-srt">
                        <span>SRT</span>
                    </label>
                    <label class="merge-checkbox-label" for="fmt-vtt-${job.id}">
                        <input type="checkbox" id="fmt-vtt-${job.id}" class="fmt-cb-vtt">
                        <span>VTT</span>
                    </label>
                    <label class="merge-checkbox-label" for="fmt-ttml-${job.id}">
                        <input type="checkbox" id="fmt-ttml-${job.id}" class="fmt-cb-ttml">
                        <span>TTML</span>
                    </label>
                    <label class="merge-checkbox-label" for="fmt-sbv-${job.id}">
                        <input type="checkbox" id="fmt-sbv-${job.id}" class="fmt-cb-sbv">
                        <span>SBV</span>
                    </label>
                    <label class="merge-checkbox-label" for="fmt-lrc-${job.id}">
                        <input type="checkbox" id="fmt-lrc-${job.id}" class="fmt-cb-lrc">
                        <span>LRC</span>
                    </label>
                    <label class="merge-checkbox-label" for="fmt-txt-${job.id}">
                        <input type="checkbox" id="fmt-txt-${job.id}" class="fmt-cb-txt">
                        <span>TXT</span>
                    </label>
                </div>
            </div>
            <div class="job-actions">
                <a class="btn btn-download btn-sm" href="/api/jobs/${job.id}/download">
                    ⬇ Download EPUB
                </a>
                <button class="btn btn-audio btn-sm convert-audio-btn">
                    🎵 Convert to Audio with Synced Subtitles
                </button>
                <button class="btn btn-danger btn-sm delete-job-btn">
                    🗑️ Delete
                </button>
            </div>
        `;

        card.querySelector('.delete-job-btn').addEventListener('click', () => deleteJob(job.id, () => refreshJobsList(() => {})));

        // Convert to Audio handler
        card.querySelector('.convert-audio-btn').addEventListener('click', async () => {
            const btn = card.querySelector('.convert-audio-btn');
            const merge = card.querySelector('.merge-chapters-cb').checked;
            const center = card.querySelector('.center-subtitles-cb').checked;
            
            // Read selected formats
            const formats = [];
            ['ass', 'srt', 'vtt', 'ttml', 'sbv', 'lrc', 'txt'].forEach(fmt => {
                const el = card.querySelector(`.fmt-cb-${fmt}`);
                if (el && el.checked) {
                    formats.push(fmt);
                }
            });

            if (formats.length === 0) {
                showToast('Please select at least one subtitle format.', 'error');
                return;
            }

            btn.disabled = true;
            btn.textContent = '⏳ Converting…';
            try {
                const blob = await convertJobToAudio(job.id, merge, formats, center);
                const stem = (job.book_title || job.original_filename || 'output').replace(/\.epub$/i, '');
                const zipName = `${stem}_audio_subtitles.zip`;
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = zipName;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                showToast('🎵 Audio + Subtitles exported successfully!', 'success');
            } catch (err) {
                showToast('Conversion failed: ' + err.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '🎵 Convert to Audio with Synced Subtitles';
            }
        });

        completedContainer.appendChild(card);
    });
}

export function renderFailedJobs(failedJobs, onJobUpdate) {
    const failedSection = document.getElementById('failed-section');
    const failedContainer = document.getElementById('failed-container');
    const failedCount = document.getElementById('failed-count');

    if (!failedSection || !failedContainer) return;

    if (failedJobs.length === 0) {
        failedSection.style.display = 'none';
        return;
    }

    failedSection.style.display = 'block';
    if (failedCount) failedCount.textContent = failedJobs.length;

    failedContainer.innerHTML = '';
    failedJobs.forEach(job => {
        const estHrsStr = job.estimated_total_hours 
            ? `~${job.estimated_total_hours.toFixed(1)} hrs` 
            : '—';

        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="icon">📖</span>
                        ${escapeHtml(job.book_title || job.original_filename)}
                    </div>
                    <span class="status-badge ${job.status}">${job.status === 'cancelled' ? '⊘ Cancelled' : '✗ Failed'}</span>
                </div>

                ${job.error ? `<div class="error-message">${escapeHtml(job.error)}</div>` : ''}

                <div class="progress-stats" style="margin-top: 0; margin-bottom: 1rem;">
                    <span class="progress-stat">Est. Audiobook: <strong>${estHrsStr}</strong></span>
                    <span class="progress-stat">Chapters: <strong>${job.progress?.chapter_total || '—'}</strong></span>
                </div>

                <div class="job-actions">
                    <button class="btn btn-primary btn-sm resume-job-btn">
                        ↻ Resume
                    </button>
                    <button class="btn btn-danger btn-sm delete-job-btn">
                        🗑️ Delete
                    </button>
                </div>
            </div>
        `;

        card.querySelector('.delete-job-btn').addEventListener('click', () => deleteJob(job.id, () => refreshJobsList(onJobUpdate)));
        card.querySelector('.resume-job-btn').addEventListener('click', () => triggerResumeModal(job.id, onJobUpdate));
        failedContainer.appendChild(card);
    });
}

export async function deleteJob(jobId, onSuccess) {
    const confirmed1 = await showConfirmModal(
        "Delete Job",
        "Are you sure you want to delete this job? This will delete the database entry and its audio files.",
        "Delete",
        "btn-danger"
    );
    if (!confirmed1) return;

    const confirmed2 = await showConfirmModal(
        "Confirm Deletion",
        "This action cannot be undone and will permanently purge this job and its synthesis cache. Confirm deletion?",
        "Yes, Delete Permanently",
        "btn-danger"
    );
    if (!confirmed2) return;

    try {
        await deleteJobApi(jobId);
        showToast('Job deleted successfully.', 'success');
        onSuccess();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

export async function triggerResumeModal(jobId, onJobUpdate) {
    try {
        const job = await fetchJobDetails(jobId);
        const originalConfig = job.config || {};

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        
        // Modal content HTML
        overlay.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <div class="modal-header">
                    <h3>↻ Resume Job Configuration</h3>
                    <button class="modal-close-btn">&times;</button>
                </div>
                <form id="resume-form" style="display: flex; flex-direction: column; gap: 1rem;">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-synthesizer">Synthesizer</label>
                            <select id="modal-synthesizer" name="synthesizer">
                                <option value="f5-tts" ${originalConfig.synthesizer === 'f5-tts' ? 'selected' : ''}>F5-TTS (Voice Cloning)</option>
                                <option value="kokoro" ${originalConfig.synthesizer === 'kokoro' ? 'selected' : ''}>Kokoro-82M (Built-in Voices / Formulas)</option>
                                <option value="pocket-tts" ${originalConfig.synthesizer === 'pocket-tts' ? 'selected' : ''}>PocketTTS (Lightweight CPU Cloning)</option>
                                <option value="dummy" ${originalConfig.synthesizer === 'dummy' ? 'selected' : ''}>Dummy (Silent / Testing)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-device">Device</label>
                            <select id="modal-device" name="device">
                                <option value="" ${!originalConfig.device ? 'selected' : ''}>Auto</option>
                                <option value="cuda" ${originalConfig.device === 'cuda' ? 'selected' : ''}>CUDA (GPU)</option>
                                <option value="cpu" ${originalConfig.device === 'cpu' ? 'selected' : ''}>CPU</option>
                                <option value="mps" ${originalConfig.device === 'mps' ? 'selected' : ''}>MPS (Apple Silicon)</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-speed">Speed</label>
                            <input type="number" id="modal-speed" name="speed" value="${originalConfig.speed || 1.0}" min="0.1" max="3.0" step="0.1">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-concurrency">Concurrency</label>
                            <input type="number" id="modal-concurrency" name="concurrency" value="${originalConfig.concurrency || 2}" min="1" max="16" step="1">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-max-chars">Max Chars/Chunk</label>
                            <input type="number" id="modal-max-chars" name="max_chars" value="${originalConfig.max_chars || 150}" min="50" max="500" step="10">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-frame-rate">Frame Rate (Hz)</label>
                            <input type="number" id="modal-frame-rate" name="frame_rate" value="${originalConfig.frame_rate || 24000}" min="8000" max="48000" step="1000">
                        </div>
                    </div>

                    <!-- F5-TTS Specific Fields in Modal -->
                    <div id="modal-f5-options" style="display: none;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
                            <div class="form-group" style="margin-bottom: 0;">
                                <label for="modal-nfe-step">Inference Steps (NFE)</label>
                                <input type="number" id="modal-nfe-step" name="nfe_step" value="${originalConfig.nfe_step || 32}" min="10" max="64" step="2">
                            </div>
                            <div class="form-group" style="flex-direction: row; align-items: center; gap: 0.5rem; height: 100%; align-self: flex-end; padding-bottom: 0.5rem;">
                                <input type="checkbox" id="modal-compile" name="compile" style="width: auto; margin: 0; cursor: pointer;" ${originalConfig.compile ? 'checked' : ''}>
                                <label for="modal-compile" style="margin: 0; cursor: pointer; user-select: none;">Compile Model (torch.compile)</label>
                            </div>
                        </div>
                    </div>

                    <!-- Kokoro Specific Fields in Modal -->
                    <div id="modal-kokoro-options" style="display: none; border-top: 1px solid var(--border-subtle); padding-top: 0.75rem;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
                            <div class="form-group">
                                <label>Voice Mode</label>
                                <div class="voice-mode-selector" id="modal-voice-mode-selector">
                                    <button type="button" class="mode-pill active" data-mode="single">Single Voice</button>
                                    <button type="button" class="mode-pill" data-mode="blend">Custom Blend</button>
                                </div>
                            </div>
                            <div class="form-group">
                                <label for="modal-lang-code">Language Code</label>
                                <select id="modal-lang-code" name="lang_code">
                                    <option value="a" ${originalConfig.lang_code === 'a' ? 'selected' : ''}>American English</option>
                                    <option value="b" ${originalConfig.lang_code === 'b' ? 'selected' : ''}>British English</option>
                                    <option value="e" ${originalConfig.lang_code === 'e' ? 'selected' : ''}>Spanish</option>
                                    <option value="f" ${originalConfig.lang_code === 'f' ? 'selected' : ''}>French</option>
                                    <option value="h" ${originalConfig.lang_code === 'h' ? 'selected' : ''}>Hindi</option>
                                    <option value="i" ${originalConfig.lang_code === 'i' ? 'selected' : ''}>Italian</option>
                                    <option value="j" ${originalConfig.lang_code === 'j' ? 'selected' : ''}>Japanese</option>
                                    <option value="p" ${originalConfig.lang_code === 'p' ? 'selected' : ''}>Portuguese</option>
                                    <option value="z" ${originalConfig.lang_code === 'z' ? 'selected' : ''}>Mandarin Chinese</option>
                                </select>
                            </div>
                        </div>

                        <!-- Single Voice Sub-panel -->
                        <div id="modal-kokoro-single-panel" class="kokoro-sub-panel" style="margin-top: 0.75rem;">
                            <div class="form-group" style="margin-bottom: 0;">
                                <label for="modal-voice-select">Kokoro Voice</label>
                                <select id="modal-voice-select" name="voice">
                                </select>
                            </div>
                        </div>

                        <!-- Custom Blend Sub-panel -->
                        <div id="modal-kokoro-blend-panel" class="kokoro-sub-panel" style="margin-top: 0.75rem; display: none;">
                            <div class="form-group">
                                <label>Blend Proportions Visualizer</label>
                                <div class="blend-visualizer-bar" id="modal-blend-visualizer-bar"></div>
                            </div>
                            <div class="form-group" style="margin-top: 0.5rem;">
                                <label>Blend Channels</label>
                                <div class="blend-channels-list" id="modal-blend-channels-list"></div>
                            </div>
                            <div class="form-grid" style="margin-top: 0.75rem; grid-template-columns: 1fr auto; align-items: flex-end;">
                                <div class="form-group" style="margin-bottom: 0;">
                                    <label for="modal-blend-add-select">Select Voice to Add</label>
                                    <select id="modal-blend-add-select"></select>
                                </div>
                                <button type="button" class="btn" id="modal-add-to-blend-btn" style="height: 38px;">➕ Add</button>
                            </div>
                            <div class="form-group" style="margin-top: 0.5rem; flex-direction: row; align-items: center; gap: 0.5rem;">
                                <input type="checkbox" id="modal-show-all-languages-checkbox" style="width: auto; margin: 0; cursor: pointer;">
                                <label for="modal-show-all-languages-checkbox" style="margin: 0; cursor: pointer; user-select: none;">Show voices from all languages</label>
                            </div>
                            <div class="form-group" style="margin-top: 0.75rem;">
                                <label>Voice Presets</label>
                                <div class="blend-presets-grid" id="modal-blend-presets-grid"></div>
                            </div>
                        </div>

                        <div class="form-group" style="margin-top: 0.75rem;">
                            <label for="modal-voice-formula">Voice Formula (Compiled String)</label>
                            <input type="text" id="modal-voice-formula" name="voice_formula" readonly value="${originalConfig.voice_formula || ''}" style="background: var(--bg-primary);">
                        </div>
                    </div>
                    
                    <div class="modal-footer" style="margin-top: 0.5rem;">
                        <button type="button" class="btn btn-ghost btn-sm cancel-btn">Cancel</button>
                        <button type="submit" class="btn btn-primary btn-sm submit-btn">Resume Job</button>
                    </div>
                </form>
            </div>
        `;
        
        document.body.appendChild(overlay);
        overlay.offsetHeight;
        overlay.classList.add('active');

        // Modal DOM fields
        const modalForm = overlay.querySelector('#resume-form');
        const modalSynth = overlay.querySelector('#modal-synthesizer');
        const modalF5Opts = overlay.querySelector('#modal-f5-options');
        const modalKokoroOpts = overlay.querySelector('#modal-kokoro-options');

        const elements = {
            langSelect: overlay.querySelector('#modal-lang-code'),
            showAllCheckbox: overlay.querySelector('#modal-show-all-languages-checkbox'),
            voiceSelect: overlay.querySelector('#modal-voice-select'),
            blendAddSelect: overlay.querySelector('#modal-blend-add-select'),
            blendVisualizerBar: overlay.querySelector('#modal-blend-visualizer-bar'),
            blendChannelsList: overlay.querySelector('#modal-blend-channels-list'),
            voiceFormulaInput: overlay.querySelector('#modal-voice-formula'),
            voiceModeSelector: overlay.querySelector('#modal-voice-mode-selector'),
            kokoroSinglePanel: overlay.querySelector('#modal-kokoro-single-panel'),
            kokoroBlendPanel: overlay.querySelector('#modal-kokoro-blend-panel'),
            addToBlendBtn: overlay.querySelector('#modal-add-to-blend-btn'),
            blendPresetsGrid: overlay.querySelector('#modal-blend-presets-grid')
        };

        // Setup Kokoro Mixer for Modal
        setupKokoroMixer(elements);

        // Prepopulate Kokoro initial voice in selector if appropriate
        if (originalConfig.voice) {
            elements.voiceSelect.value = originalConfig.voice;
        }

        // Hide/show options function
        function toggleModalSynthFields() {
            const synth = modalSynth.value;
            if (synth === 'f5-tts') {
                modalF5Opts.style.display = 'block';
                modalKokoroOpts.style.display = 'none';
            } else if (synth === 'kokoro') {
                modalF5Opts.style.display = 'none';
                modalKokoroOpts.style.display = 'block';
                // Trigger initial filter & layout
                updateFilteredVoices(elements);
                if (originalConfig.voice_formula) {
                    setVoiceMode('blend', elements);
                    // Parse blend formula
                    const parsed = [];
                    const segments = originalConfig.voice_formula.split('+');
                    segments.forEach(seg => {
                        const parts = seg.split('*');
                        if (parts.length === 2) {
                            parsed.push({ voice: parts[0], weight: parseFloat(parts[1]) * 100 });
                        }
                    });
                    // Set blend voices state on elements for tracking
                    // (To avoid modifying global state, we can store it on elements' visualizer container)
                    elements.blendVisualizerBar.activeBlendVoices = parsed;
                    // Hook into renderBlendMixer override to read from container
                    // Let's customize state per-instance
                } else {
                    setVoiceMode('single', elements);
                }
            } else {
                modalF5Opts.style.display = 'none';
                modalKokoroOpts.style.display = 'none';
            }
        }

        modalSynth.addEventListener('change', toggleModalSynthFields);
        toggleModalSynthFields();

        // Close logic
        function closeModal() {
            overlay.classList.remove('active');
            setTimeout(() => overlay.remove(), 300);
        }

        overlay.querySelector('.modal-close-btn').addEventListener('click', closeModal);
        overlay.querySelector('.cancel-btn').addEventListener('click', closeModal);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });

        // Submit logic
        modalForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData();
            formData.append('synthesizer', modalSynth.value);
            formData.append('device', modalForm.querySelector('#modal-device').value);
            formData.append('speed', modalForm.querySelector('#modal-speed').value);
            formData.append('concurrency', modalForm.querySelector('#modal-concurrency').value);
            formData.append('max_chars', modalForm.querySelector('#modal-max-chars').value);
            formData.append('frame_rate', modalForm.querySelector('#modal-frame-rate').value);

            if (modalSynth.value === 'f5-tts') {
                formData.append('nfe_step', modalForm.querySelector('#modal-nfe-step').value);
                formData.append('compile', modalForm.querySelector('#modal-compile').checked);
            } else if (modalSynth.value === 'kokoro') {
                const currentMode = elements.voiceModeSelector.querySelector('.mode-pill.active').getAttribute('data-mode');
                formData.append('lang_code', elements.langSelect.value);
                if (currentMode === 'single') {
                    formData.append('voice', elements.voiceSelect.value);
                    formData.append('voice_formula', '');
                } else {
                    formData.append('voice', '');
                    formData.append('voice_formula', elements.voiceFormulaInput.value);
                }
            }

            closeModal();

            try {
                await resumeJobApi(jobId, formData);
                showToast('Resuming job...', 'success');
                refreshJobsList(onJobUpdate);
            } catch (err) {
                showToast(err.message, 'error');
            }
        });

    } catch (err) {
        showToast('Failed to retrieve job information.', 'error');
    }
}
