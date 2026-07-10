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

// Extract mode DOM references
const extractForm = document.getElementById('extract-form');
const extractSubmitBtn = document.getElementById('extract-submit-btn');
const extractEpubFile = document.getElementById('extract-epub-file');
const extractEpubUploadZone = document.getElementById('extract-epub-upload-zone');
const extractEpubFileName = document.getElementById('extract-epub-file-name');
const extractStatus = document.getElementById('extract-status');
const extractStatusTitle = document.getElementById('extract-status-title');
const extractStatusBadge = document.getElementById('extract-status-badge');
const extractStatusMessage = document.getElementById('extract-status-message');

// Tab references
const tabGenerate = document.getElementById('tab-generate');
const tabExtract = document.getElementById('tab-extract');
const modeGenerate = document.getElementById('mode-generate');
const modeExtract = document.getElementById('mode-extract');

// ── State ──
let activeSSE = null;
let jobs = [];
let activeVoiceMode = 'single';
let activeBlendVoices = [];
let previewAudio = null;

// ── Initialize ──
document.addEventListener('DOMContentLoaded', async () => {
    await fetchConfig();
    loadJobs();
    setupFileUploads();
    setupSynthesizerToggle();
    setupChapterSelection();
    setupForm();
    setupTabs();
    setupExtractForm();
    startStatsPolling();
    setupKokoroMixer();
    
    const purgeBtn = document.getElementById('purge-cache-btn');
    if (purgeBtn) {
        purgeBtn.addEventListener('click', purgeAllCache);
    }
});

// ── Tab Switching ──
function setupTabs() {
    tabGenerate.addEventListener('click', () => {
        tabGenerate.classList.add('active');
        tabExtract.classList.remove('active');
        modeGenerate.style.display = 'block';
        modeExtract.style.display = 'none';
    });

    tabExtract.addEventListener('click', () => {
        tabExtract.classList.add('active');
        tabGenerate.classList.remove('active');
        modeExtract.style.display = 'block';
        modeGenerate.style.display = 'none';
    });
}

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
    // Extract EPUB file
    setupDropZone(extractEpubUploadZone, extractEpubFile, extractEpubFileName);
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
            input.dispatchEvent(new Event('change'));
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
    const cloningOptions = document.getElementById('cloning-options');
    const f5TtsOptions = document.getElementById('f5-tts-options');
    const kokoroOptions = document.getElementById('kokoro-options');

    function toggleFields() {
        const val = synthSelect.value;
        if (val === 'f5-tts') {
            cloningOptions.style.display = 'block';
            f5TtsOptions.style.display = 'block';
            kokoroOptions.style.display = 'none';
        } else if (val === 'pocket-tts') {
            cloningOptions.style.display = 'block';
            f5TtsOptions.style.display = 'none';
            kokoroOptions.style.display = 'none';
        } else if (val === 'kokoro') {
            cloningOptions.style.display = 'none';
            f5TtsOptions.style.display = 'none';
            kokoroOptions.style.display = 'block';
            setVoiceMode(activeVoiceMode);
        } else {
            cloningOptions.style.display = 'none';
            f5TtsOptions.style.display = 'none';
            kokoroOptions.style.display = 'none';
        }
    }

    synthSelect.addEventListener('change', toggleFields);
    toggleFields();
}

// ── Form Submission ──
function setupForm() {
    jobForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(jobForm);

        // Adjust Kokoro parameters based on active voice mode
        if (synthSelect.value === 'kokoro') {
            if (activeVoiceMode === 'single') {
                const vs = document.getElementById('voice-select');
                formData.set('voice', vs ? vs.value : '');
                formData.set('voice_formula', '');
            } else {
                formData.set('voice', '');
                const vfi = document.getElementById('voice-formula-input');
                formData.set('voice_formula', vfi ? vfi.value : '');
            }
        }

        // Validation
        if (!epubFile.files.length) {
            showToast('Please select an EPUB file.', 'error');
            return;
        }

        const selectedSynth = synthSelect.value;
        if (selectedSynth === 'f5-tts') {
            if (!refAudioFile.files.length) {
                showToast('Reference audio is required for F5-TTS.', 'error');
                return;
            }
            if (!formData.get('ref_text')?.trim()) {
                showToast('Reference text is required for F5-TTS.', 'error');
                return;
            }
        } else if (selectedSynth === 'pocket-tts') {
            if (!refAudioFile.files.length) {
                showToast('Reference audio is required for PocketTTS.', 'error');
                return;
            }
        } else if (selectedSynth === 'kokoro') {
            if (!formData.get('voice') && !formData.get('voice_formula')?.trim()) {
                showToast('Either voice or voice formula must be specified for Kokoro.', 'error');
                return;
            }
        }

        // Add selected chapters as a JSON array
        const selected = [];
        document.querySelectorAll('.chapter-checkbox:checked').forEach(cb => {
            selected.push(cb.getAttribute('data-idref'));
        });
        formData.append('selected_chapters', JSON.stringify(selected));

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
            
            // Hide chapter selection panel
            document.getElementById('chapter-selection-panel').style.display = 'none';
            document.getElementById('chapters-list-wrapper').innerHTML = '';

            // Reset dynamic fields
            const cloningOptions = document.getElementById('cloning-options');
            const f5TtsOptions = document.getElementById('f5-tts-options');
            const kokoroOptions = document.getElementById('kokoro-options');
            cloningOptions.style.display = 'block';
            f5TtsOptions.style.display = 'block';
            kokoroOptions.style.display = 'none';

            // Reset custom Kokoro voice mixer state
            activeVoiceMode = 'single';
            activeBlendVoices = [];
            if (previewAudio) {
                previewAudio.pause();
                previewAudio = null;
            }
            updatePreviewButtonState(false);
            setVoiceMode('single');
            updateFilteredVoices();

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

// ── Extract Form ──
function setupExtractForm() {
    extractForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!extractEpubFile.files.length) {
            showToast('Please select an EPUB file.', 'error');
            return;
        }

        extractSubmitBtn.disabled = true;
        extractSubmitBtn.innerHTML = '<span class="spinner"></span> Extracting...';

        // Show status card
        extractStatus.style.display = 'block';
        extractStatusTitle.textContent = 'Extracting Audio + LRC...';
        extractStatusBadge.className = 'phase-badge synthesizing';
        extractStatusBadge.querySelector('.phase-text').textContent = 'Processing';
        extractStatusMessage.textContent = 'Uploading and processing EPUB file...';
        extractStatusMessage.style.display = 'block';

        const formData = new FormData();
        formData.append('epub', extractEpubFile.files[0]);
        formData.append('merge', document.getElementById('extract-merge-checkbox').checked);

        try {
            const resp = await fetch('/api/extract', {
                method: 'POST',
                body: formData,
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || 'Extraction failed');
            }

            // Download the ZIP file
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const filename = extractEpubFile.files[0].name.replace('.epub', '') + '_audio_lrc.zip';

            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

            // Update status
            extractStatusTitle.textContent = 'Extraction Complete!';
            extractStatusBadge.className = 'phase-badge done';
            extractStatusBadge.innerHTML = '<span class="phase-text">Done</span>';
            extractStatusMessage.textContent = `✓ Downloaded ${filename}`;

            showToast('Audio + LRC extracted successfully!', 'success');

            // Reset form
            extractForm.reset();
            extractEpubFileName.style.display = 'none';

        } catch (err) {
            extractStatusTitle.textContent = 'Extraction Failed';
            extractStatusBadge.className = 'phase-badge error';
            extractStatusBadge.innerHTML = '<span class="phase-text">Error</span>';
            extractStatusMessage.textContent = `✗ ${err.message}`;

            showToast(err.message, 'error');
        } finally {
            extractSubmitBtn.disabled = false;
            extractSubmitBtn.innerHTML = '📤 Extract Audio + LRC';
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

    // Chunk progress
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

    // ETA calculation
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

                <!-- Overall Book Progress -->
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

                <!-- Active Synthesis Progress -->
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
                synthBar.style.background = 'linear-gradient(135deg, #f43f5e, #fb923c)';
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

        // Actual or fallback estimated audiobook length
        const audiobookLength = job.audiobook_duration_seconds 
            ? formatTime(job.audiobook_duration_seconds)
            : (job.estimated_total_hours ? `~${job.estimated_total_hours.toFixed(1)} hrs` : '—');

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
                    <span class="progress-stat">Audiobook Length: <strong>${audiobookLength}</strong></span>
                    <span class="progress-stat">Compute Time: <strong>${duration}</strong></span>
                    <span class="progress-stat">Chapters: <strong>${job.progress?.chapter_total || '—'}</strong></span>
                </div>

                ${audioHTML}

                <div class="job-actions">
                    <a class="btn btn-download btn-sm" href="/api/jobs/${job.id}/download">
                        ⬇ Download EPUB
                    </a>
                    <button class="btn btn-danger btn-sm" onclick="deleteJob('${job.id}')">
                        🗑️ Delete
                    </button>
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

    failedContainer.innerHTML = failedJobs.map(job => {
        const estHrsStr = job.estimated_total_hours 
            ? `~${job.estimated_total_hours.toFixed(1)} hrs` 
            : '—';

        return `
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
                <button class="btn btn-primary btn-sm" onclick="resumeJob('${job.id}')">
                    ↻ Resume
                </button>
                <button class="btn btn-danger btn-sm" onclick="deleteJob('${job.id}')">
                    🗑️ Delete
                </button>
            </div>
        </div>
        `;
    }).join('');
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

// ── Resume Job ──
async function resumeJob(jobId) {
    try {
        const resp = await fetch(`/api/jobs/${jobId}`);
        if (!resp.ok) {
            showToast('Failed to fetch job details.', 'error');
            return;
        }
        const job = await resp.json();
        const originalConfig = job.config || {};

        // Create overlay element
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        
        // Modal content HTML
        overlay.innerHTML = `
            <div class="modal-content">
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
                            <label for="modal-nfe-step">Inference Steps (NFE)</label>
                            <input type="number" id="modal-nfe-step" name="nfe_step" value="${originalConfig.nfe_step || 32}" min="10" max="64" step="2">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label for="modal-max-chars">Max Chars/Chunk</label>
                            <input type="number" id="modal-max-chars" name="max_chars" value="${originalConfig.max_chars || 150}" min="50" max="500" step="10">
                        </div>
                    </div>
                    
                    <div class="form-group" style="flex-direction: row; align-items: center; gap: 0.5rem; margin-bottom: 0;">
                        <input type="checkbox" id="modal-compile" name="compile" style="width: auto; margin: 0; cursor: pointer;" ${originalConfig.compile ? 'checked' : ''}>
                        <label for="modal-compile" style="margin: 0; cursor: pointer; user-select: none; text-transform: none;">Compile Model (torch.compile)</label>
                    </div>

                    <div class="modal-footer" style="margin-top: 0.5rem;">
                        <button type="button" class="btn btn-ghost btn-sm cancel-btn">Cancel</button>
                        <button type="submit" class="btn btn-primary btn-sm submit-btn">Resume Job</button>
                    </div>
                </form>
            </div>
        `;
        
        document.body.appendChild(overlay);
        
        // Trigger reflow to animate opacity/translate
        overlay.offsetHeight;
        overlay.classList.add('active');

        const form = overlay.querySelector('#resume-form');
        const submitBtnEl = form.querySelector('.submit-btn');
        const closeBtn = overlay.querySelector('.modal-close-btn');
        const cancelBtn = overlay.querySelector('.cancel-btn');

        // Check if options differ from the original configuration
        function checkChanges() {
            const currentSynth = form.querySelector('#modal-synthesizer').value;
            const currentDevice = form.querySelector('#modal-device').value;
            const currentSpeed = parseFloat(form.querySelector('#modal-speed').value);
            const currentConcurrency = parseInt(form.querySelector('#modal-concurrency').value);
            const currentNfe = parseInt(form.querySelector('#modal-nfe-step').value);
            const currentMaxChars = parseInt(form.querySelector('#modal-max-chars').value);
            const currentCompile = form.querySelector('#modal-compile').checked;

            const hasChanged = 
                currentSynth !== (originalConfig.synthesizer || 'f5-tts') ||
                currentDevice !== (originalConfig.device || '') ||
                currentSpeed !== (originalConfig.speed || 1.0) ||
                currentConcurrency !== (originalConfig.concurrency || 2) ||
                currentNfe !== (originalConfig.nfe_step || 32) ||
                currentMaxChars !== (originalConfig.max_chars || 150) ||
                currentCompile !== !!originalConfig.compile;

            if (hasChanged) {
                submitBtnEl.textContent = 'Resume Job with New Options';
            } else {
                submitBtnEl.textContent = 'Resume Job';
            }
        }

        // Add input/change listeners
        form.querySelectorAll('input, select').forEach(el => {
            el.addEventListener('input', checkChanges);
            el.addEventListener('change', checkChanges);
        });

        // Close functions
        function closeModal() {
            overlay.classList.remove('active');
            setTimeout(() => {
                overlay.remove();
            }, 300);
        }

        closeBtn.onclick = closeModal;
        cancelBtn.onclick = closeModal;
        overlay.onclick = (e) => {
            if (e.target === overlay) closeModal();
        };

        // Submit form handler
        form.onsubmit = async (e) => {
            e.preventDefault();
            
            const formData = new FormData();
            formData.append('synthesizer', form.querySelector('#modal-synthesizer').value);
            formData.append('device', form.querySelector('#modal-device').value);
            formData.append('speed', form.querySelector('#modal-speed').value);
            formData.append('concurrency', form.querySelector('#modal-concurrency').value);
            formData.append('nfe_step', form.querySelector('#modal-nfe-step').value);
            formData.append('max_chars', form.querySelector('#modal-max-chars').value);
            formData.append('compile', form.querySelector('#modal-compile').checked);

            closeModal();

            try {
                const resp = await fetch(`/api/jobs/${jobId}/resume`, {
                    method: 'POST',
                    body: formData
                });
                if (!resp.ok) {
                    const err = await resp.json();
                    showToast(err.detail || 'Failed to resume', 'error');
                } else {
                    showToast('Resuming job...', 'success');
                    loadJobs();
                }
            } catch (err) {
                showToast('Failed to resume job.', 'error');
            }
        };

    } catch (err) {
        showToast('Failed to retrieve job information.', 'error');
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

        // Cache Size
        try {
            const cacheResp = await fetch('/api/cache/size');
            if (cacheResp.ok) {
                const cacheData = await cacheResp.json();
                const sizeMb = (cacheData.size_bytes / (1024 * 1024)).toFixed(2);
                document.getElementById('stat-cache').textContent = `${sizeMb} MB`;
            }
        } catch (cacheErr) {
            console.error('Failed to fetch cache size:', cacheErr);
        }
    } catch (err) {
        console.error('Failed to fetch resource stats:', err);
    }
}

// ── Custom Confirmation Modal Helper ──
function showConfirmModal(title, message, confirmText = 'Confirm', confirmClass = 'btn-primary') {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <h3>${title}</h3>
                    <button class="modal-close-btn">&times;</button>
                </div>
                <div style="margin-bottom: 1.5rem; font-size: 0.95rem; line-height: 1.5; color: var(--text-secondary);">
                    ${message}
                </div>
                <div style="display: flex; justify-content: flex-end; gap: 0.75rem;">
                    <button class="btn btn-ghost modal-cancel-btn">Cancel</button>
                    <button class="btn ${confirmClass} modal-confirm-btn">${confirmText}</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        
        // Force reflow and activate transition
        overlay.offsetHeight;
        overlay.classList.add('active');

        const cleanUp = () => {
            overlay.classList.remove('active');
            setTimeout(() => {
                overlay.remove();
            }, 300);
        };

        overlay.querySelector('.modal-close-btn').addEventListener('click', () => {
            cleanUp();
            resolve(false);
        });

        overlay.querySelector('.modal-cancel-btn').addEventListener('click', () => {
            cleanUp();
            resolve(false);
        });

        overlay.querySelector('.modal-confirm-btn').addEventListener('click', () => {
            cleanUp();
            resolve(true);
        });

        // Close on clicking outside modal content
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                cleanUp();
                resolve(false);
            }
        });
    });
}

// ── Delete Job (with confirmation) ──
async function deleteJob(jobId) {
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
        const resp = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
        if (resp.ok) {
            showToast('Job deleted successfully.', 'success');
            loadJobs(); // Refresh jobs
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Failed to delete job.', 'error');
        }
    } catch (err) {
        showToast('Failed to delete job.', 'error');
    }
}

// ── Purge All Cache (with confirmation) ──
async function purgeAllCache() {
    let sizeStr = "";
    try {
        const sizeResp = await fetch('/api/cache/size');
        if (sizeResp.ok) {
            const sizeData = await sizeResp.json();
            const sizeMb = (sizeData.size_bytes / (1024 * 1024)).toFixed(2);
            sizeStr = ` (estimated cache size: ${sizeMb} MB)`;
        }
    } catch (err) {
        console.error('Failed to get cache size:', err);
    }

    const confirmed1 = await showConfirmModal(
        "Purge All Cache",
        `Are you sure you want to clear all pipeline cache and jobs?${sizeStr}`,
        "Purge All",
        "btn-danger"
    );
    if (!confirmed1) return;

    const confirmed2 = await showConfirmModal(
        "Confirm Purge",
        "This will permanently delete all cached chapter audio/SMIL data and all non-running jobs. Are you absolutely sure?",
        "Yes, Purge Everything",
        "btn-danger"
    );
    if (!confirmed2) return;

    try {
        const resp = await fetch('/api/cache', { method: 'DELETE' });
        if (resp.ok) {
            showToast('All caches and non-running jobs purged.', 'success');
            loadJobs(); // Refresh jobs
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Failed to purge cache.', 'error');
        }
    } catch (err) {
        showToast('Failed to purge cache.', 'error');
    }
}

// ── Multi-model and Chapter Selection Helpers ──

let kokoroVoices = [];

async function fetchConfig() {
    try {
        const resp = await fetch('/api/config');
        if (resp.ok) {
            const data = await resp.json();
            kokoroVoices = data.kokoro_voices || [];
            populateKokoroVoices();
        }
    } catch (err) {
        console.error('Failed to fetch config:', err);
    }
}

function populateKokoroVoices() {
    updateFilteredVoices();
}

function setupChapterSelection() {
    epubFile.addEventListener('change', async () => {
        if (!epubFile.files.length) {
            document.getElementById('chapter-selection-panel').style.display = 'none';
            return;
        }
        const file = epubFile.files[0];
        const selectionPanel = document.getElementById('chapter-selection-panel');
        const wrapper = document.getElementById('chapters-list-wrapper');

        selectionPanel.style.display = 'block';
        wrapper.innerHTML = '<div class="loading-chapters" style="padding: 1rem; text-align: center; color: var(--text-secondary);"><span class="spinner" style="display:inline-block; width:1rem; height:1rem; border:2px solid var(--text-secondary); border-top-color:transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:0.5rem; vertical-align:middle;"></span> Extracting chapters...</div>';

        const formData = new FormData();
        formData.append('epub', file);

        try {
            const resp = await fetch('/api/chapters', {
                method: 'POST',
                body: formData
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || 'Failed to load chapters');
            }
            const chapters = await resp.json();
            renderChaptersList(chapters);
        } catch (err) {
            showToast(err.message, 'error');
            wrapper.innerHTML = `<div class="error-chapters" style="padding: 1rem; color: var(--danger); text-align: center;">✗ Error loading chapters: ${err.message}</div>`;
        }
    });

    document.getElementById('select-all-chapters-btn').addEventListener('click', () => {
        document.querySelectorAll('.chapter-checkbox').forEach(cb => cb.checked = true);
    });

    document.getElementById('deselect-all-chapters-btn').addEventListener('click', () => {
        document.querySelectorAll('.chapter-checkbox').forEach(cb => cb.checked = false);
    });

    const wrapper = document.getElementById('chapters-list-wrapper');
    wrapper.addEventListener('click', (e) => {
        if (e.target.classList.contains('toggle-preview-btn')) {
            const btn = e.target;
            const row = btn.closest('.chapter-item-row');
            const container = row.querySelector('.chapter-preview-container');
            const isHidden = container.classList.toggle('hidden');
            btn.textContent = isHidden ? 'Show Preview' : 'Hide Preview';
        }
    });
}

function renderChaptersList(chapters) {
    const wrapper = document.getElementById('chapters-list-wrapper');
    wrapper.innerHTML = '';
    if (!chapters || chapters.length === 0) {
        wrapper.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--text-secondary);">No processable chapters found.</div>';
        return;
    }

    chapters.forEach(ch => {
        const titleLower = ch.title.toLowerCase();
        const skipPatterns = ["note", "reference", "copyright", "index", "acknowledg", "bibliograph", "appendix", "about the author", "title page", "colophon"];
        const isSkip = skipPatterns.some(p => titleLower.includes(p));
        const checkedAttr = isSkip ? '' : 'checked';

        const item = document.createElement('div');
        item.className = 'chapter-item-row';
        item.innerHTML = `
            <div class="chapter-item-header" style="display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid var(--border-color); gap: 1rem;">
                <label class="chapter-checkbox-label" style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer; flex: 1; user-select: none; margin: 0; text-transform: none;">
                    <input type="checkbox" class="chapter-checkbox" data-idref="${ch.idref}" ${checkedAttr} style="width: auto; margin: 0; cursor: pointer;">
                    <span class="chapter-title" style="font-weight: 500; font-size: 0.9rem;">${ch.title}</span>
                </label>
                <span class="chapter-char-count" style="font-size: 0.8rem; color: var(--text-secondary); white-space: nowrap;">${ch.char_count} chars</span>
                <button type="button" class="btn btn-xs btn-ghost toggle-preview-btn" style="white-space: nowrap; font-size: 0.8rem; padding: 0.2rem 0.5rem; line-height: 1.2;">Show Preview</button>
            </div>
            <div class="chapter-preview-container hidden" style="padding: 0.75rem; background: var(--bg-secondary); border-radius: 4px; margin-top: 0.25rem;">
                <pre class="chapter-preview-text" style="margin: 0; font-family: inherit; font-size: 0.8rem; white-space: pre-wrap; word-break: break-all; color: var(--text-secondary); max-height: 200px; overflow-y: auto;">${ch.preview || 'No text preview available.'}</pre>
            </div>
        `;
        wrapper.appendChild(item);
    });
}


// ── Kokoro Custom Blend Mixer & Previews ──

const LANG_PREFIX_MAP = {
    'a': ['af_', 'am_'],
    'b': ['bf_', 'bm_'],
    'e': ['ef_', 'em_'],
    'f': ['ff_'],
    'h': ['hf_', 'hm_'],
    'i': ['if_', 'im_'],
    'j': ['jf_', 'jm_'],
    'p': ['pf_', 'pm_'],
    'z': ['zf_', 'zm_']
};

const BLEND_COLORS = [
    '#8b5cf6', // Violet
    '#06b6d4', // Cyan
    '#10b981', // Emerald
    '#f43f5e', // Rose
    '#f59e0b', // Amber
    '#3b82f6', // Blue
    '#f97316', // Orange
    '#a855f7'  // Purple
];

const KOKORO_PRESETS = [
    {
        name: "Warm Narrative Duet (US)",
        desc: "Balanced male and female US voices for engaging stories",
        formula: "af_heart*0.5+am_adam*0.5"
    },
    {
        name: "UK Storyteller Duo",
        desc: "Cozy blend of Lily and Fable for standard narration",
        formula: "bf_lily*0.6+bm_fable*0.4"
    },
    {
        name: "Deep Dramatic (US)",
        desc: "Deeper, atmospheric male voices with a hint of female brightness",
        formula: "am_onyx*0.6+am_michael*0.3+af_sarah*0.1"
    },
    {
        name: "Cozy Fireside (US)",
        desc: "Warm female voices blended for a soft reading tone",
        formula: "af_bella*0.4+af_sky*0.4+af_heart*0.2"
    }
];

function getSegmentColor(index) {
    return BLEND_COLORS[index % BLEND_COLORS.length];
}

function getVoiceMetadata(voiceName) {
    const langMap = {
        'af': { name: 'US English', gender: 'Female' },
        'am': { name: 'US English', gender: 'Male' },
        'bf': { name: 'UK English', gender: 'Female' },
        'bm': { name: 'UK English', gender: 'Male' },
        'ef': { name: 'Spanish', gender: 'Female' },
        'em': { name: 'Spanish', gender: 'Male' },
        'ff': { name: 'French', gender: 'Female' },
        'hf': { name: 'Hindi', gender: 'Female' },
        'hm': { name: 'Hindi', gender: 'Male' },
        'if': { name: 'Italian', gender: 'Female' },
        'im': { name: 'Italian', gender: 'Male' },
        'jf': { name: 'Japanese', gender: 'Female' },
        'jm': { name: 'Japanese', gender: 'Male' },
        'pf': { name: 'Portuguese', gender: 'Female' },
        'pm': { name: 'Portuguese', gender: 'Male' },
        'zf': { name: 'Chinese', gender: 'Female' },
        'zm': { name: 'Chinese', gender: 'Male' }
    };
    const prefix = voiceName.substring(0, 2);
    const meta = langMap[prefix] || { name: 'Unknown Language', gender: 'Unknown' };
    
    // Capitalize name part
    let namePart = voiceName.substring(3);
    namePart = namePart.charAt(0).toUpperCase() + namePart.slice(1);
    
    return {
        id: voiceName,
        displayName: `${namePart} (${meta.name} ${meta.gender})`,
        langName: meta.name,
        gender: meta.gender
    };
}

function updateFilteredVoices() {
    const langSelect = document.getElementById('lang-code-select');
    if (!langSelect) return;
    
    const langCode = langSelect.value;
    const showAllCheckbox = document.getElementById('show-all-languages-checkbox');
    const showAll = showAllCheckbox ? showAllCheckbox.checked : false;
    
    const prefixes = LANG_PREFIX_MAP[langCode] || [];
    
    const filtered = kokoroVoices.filter(voice => {
        if (showAll) return true;
        return prefixes.some(p => voice.startsWith(p));
    });
    
    // 1. Update Single Voice Selector
    const voiceSelect = document.getElementById('voice-select');
    if (voiceSelect) {
        const prevSelected = voiceSelect.value;
        voiceSelect.innerHTML = '';
        
        filtered.forEach(voice => {
            const meta = getVoiceMetadata(voice);
            const opt = document.createElement('option');
            opt.value = voice;
            opt.textContent = meta.displayName;
            if (voice === prevSelected || (!prevSelected && voice === 'af_heart')) {
                opt.selected = true;
            }
            voiceSelect.appendChild(opt);
        });
        
        if (!voiceSelect.value && filtered.length > 0) {
            voiceSelect.selectedIndex = 0;
        }
    }
    
    // 2. Update Blend Add Selector
    const blendAddSelect = document.getElementById('blend-add-select');
    if (blendAddSelect) {
        const prevSelectedAdd = blendAddSelect.value;
        blendAddSelect.innerHTML = '';
        
        const activeIds = activeBlendVoices.map(v => v.voice);
        const addable = filtered.filter(voice => !activeIds.includes(voice));
        
        addable.forEach(voice => {
            const meta = getVoiceMetadata(voice);
            const opt = document.createElement('option');
            opt.value = voice;
            opt.textContent = meta.displayName;
            if (voice === prevSelectedAdd) {
                opt.selected = true;
            }
            blendAddSelect.appendChild(opt);
        });
    }
}

function renderBlendMixer() {
    const bar = document.getElementById('blend-visualizer-bar');
    const list = document.getElementById('blend-channels-list');
    const formulaInput = document.getElementById('voice-formula-input');
    
    if (!bar || !list) return;
    
    bar.innerHTML = '';
    list.innerHTML = '';
    
    if (activeBlendVoices.length === 0) {
        bar.innerHTML = `<div class="blend-visualizer-empty">No voices in mix. Add a voice below!</div>`;
        if (formulaInput) formulaInput.value = '';
        return;
    }
    
    const totalWeight = activeBlendVoices.reduce((sum, v) => sum + v.weight, 0);
    
    activeBlendVoices.forEach((item, index) => {
        const color = getSegmentColor(index);
        const meta = getVoiceMetadata(item.voice);
        const proportion = totalWeight > 0 ? (item.weight / totalWeight) : 0;
        const percentage = (proportion * 100).toFixed(0);
        
        // 1. Add to visualizer bar
        if (proportion > 0) {
            const seg = document.createElement('div');
            seg.className = 'blend-visualizer-segment';
            seg.style.width = `${proportion * 100}%`;
            seg.style.backgroundColor = color;
            seg.textContent = `${percentage}% ${item.voice}`;
            seg.title = `${meta.displayName}: ${percentage}%`;
            bar.appendChild(seg);
        }
        
        // 2. Add slider row
        const row = document.createElement('div');
        row.className = 'blend-channel-row';
        row.innerHTML = `
            <div class="blend-channel-color-badge" style="color: ${color}"></div>
            <div class="blend-channel-info">
                <div class="blend-channel-name">${item.voice}</div>
                <div class="blend-channel-desc">${meta.displayName}</div>
            </div>
            <div class="blend-channel-slider-container">
                <input type="range" class="blend-channel-slider" min="1" max="100" value="${item.weight}">
            </div>
            <div class="blend-channel-percent">${percentage}%</div>
            <button type="button" class="blend-channel-remove" title="Remove voice">✕</button>
        `;
        
        const slider = row.querySelector('.blend-channel-slider');
        slider.addEventListener('input', (e) => {
            item.weight = parseFloat(e.target.value);
            renderBlendMixer();
        });
        
        const removeBtn = row.querySelector('.blend-channel-remove');
        removeBtn.addEventListener('click', () => {
            activeBlendVoices.splice(index, 1);
            renderBlendMixer();
            updateFilteredVoices();
        });
        
        list.appendChild(row);
    });
    
    // 3. Compile formula
    const formulaParts = activeBlendVoices.map(item => {
        const proportion = totalWeight > 0 ? (item.weight / totalWeight) : 0;
        return `${item.voice}*${proportion.toFixed(2)}`;
    });
    if (formulaInput) {
        formulaInput.value = formulaParts.join('+');
    }
}

function addVoiceToBlend() {
    const select = document.getElementById('blend-add-select');
    if (!select) return;
    const voice = select.value;
    if (!voice) return;
    
    if (activeBlendVoices.some(v => v.voice === voice)) {
        showToast('Voice is already in the mix!', 'error');
        return;
    }
    
    activeBlendVoices.push({ voice, weight: 50 });
    
    renderBlendMixer();
    updateFilteredVoices();
}

function applyPreset(formula) {
    const parsed = [];
    const segments = formula.split('+');
    segments.forEach(seg => {
        const parts = seg.trim().split('*');
        if (parts.length === 2) {
            const voice = parts[0].trim();
            const weight = parseFloat(parts[1].trim()) * 100;
            parsed.push({ voice, weight });
        }
    });
    
    if (parsed.length > 0) {
        activeBlendVoices = parsed;
        setVoiceMode('blend');
        renderBlendMixer();
        updateFilteredVoices();
        showToast('Preset applied successfully!', 'success');
    }
}

function renderPresets() {
    const grid = document.getElementById('blend-presets-grid');
    if (!grid) return;
    grid.innerHTML = '';
    
    KOKORO_PRESETS.forEach(preset => {
        const card = document.createElement('div');
        card.className = 'blend-preset-card';
        card.innerHTML = `
            <div class="blend-preset-title">${preset.name}</div>
            <div class="blend-preset-desc">${preset.desc}</div>
        `;
        card.addEventListener('click', () => {
            applyPreset(preset.formula);
        });
        grid.appendChild(card);
    });
}

function setVoiceMode(mode) {
    activeVoiceMode = mode;
    
    const selector = document.getElementById('voice-mode-selector');
    if (selector) {
        selector.querySelectorAll('.mode-pill').forEach(btn => {
            if (btn.getAttribute('data-mode') === mode) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }
    
    const singlePanel = document.getElementById('kokoro-single-panel');
    const blendPanel = document.getElementById('kokoro-blend-panel');
    
    if (mode === 'single') {
        if (singlePanel) singlePanel.style.display = 'block';
        if (blendPanel) blendPanel.style.display = 'none';
    } else {
        if (singlePanel) singlePanel.style.display = 'none';
        if (blendPanel) blendPanel.style.display = 'block';
        
        if (activeBlendVoices.length === 0) {
            const voiceSelect = document.getElementById('voice-select');
            const defaultVoice = voiceSelect ? voiceSelect.value : 'af_heart';
            activeBlendVoices.push({ voice: defaultVoice || 'af_heart', weight: 100 });
            renderBlendMixer();
        }
    }
}

async function playVoicePreview() {
    const playBtn = document.getElementById('play-preview-btn');
    const textInput = document.getElementById('preview-text-input');
    const langSelect = document.getElementById('lang-code-select');
    
    if (!playBtn) return;
    
    if (previewAudio && !previewAudio.paused) {
        previewAudio.pause();
        previewAudio = null;
        updatePreviewButtonState(false);
        return;
    }
    
    const text = textInput ? textInput.value.trim() : '';
    if (!text) {
        showToast('Please enter some text to preview.', 'error');
        return;
    }
    
    let voice = '';
    let voiceFormula = '';
    
    if (activeVoiceMode === 'single') {
        const voiceSelect = document.getElementById('voice-select');
        voice = voiceSelect ? voiceSelect.value : '';
        if (!voice) {
            showToast('Please select a voice to preview.', 'error');
            return;
        }
    } else {
        const formulaInput = document.getElementById('voice-formula-input');
        voiceFormula = formulaInput ? formulaInput.value : '';
        if (!voiceFormula) {
            showToast('Please mix some voices to preview.', 'error');
            return;
        }
    }
    
    const langCode = langSelect ? langSelect.value : 'a';
    
    playBtn.disabled = true;
    playBtn.innerHTML = '<span class="spinner" style="display:inline-block; width:0.8rem; height:0.8rem; border:2px solid #fff; border-top-color:transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:0.25rem; vertical-align:middle;"></span> Synthesizing...';
    
    try {
        const body = new FormData();
        body.append('voice', voice);
        body.append('voice_formula', voiceFormula);
        body.append('lang_code', langCode);
        body.append('text', text);
        
        const resp = await fetch('/api/preview', {
            method: 'POST',
            body: body
        });
        
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Failed to generate preview.');
        }
        
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        
        previewAudio = new Audio(url);
        previewAudio.addEventListener('ended', () => {
            updatePreviewButtonState(false);
            previewAudio = null;
        });
        
        previewAudio.addEventListener('pause', () => {
            updatePreviewButtonState(false);
        });
        
        updatePreviewButtonState(true);
        playBtn.disabled = false;
        await previewAudio.play();
        
    } catch (err) {
        showToast(err.message || 'Failed to play preview.', 'error');
        updatePreviewButtonState(false);
        playBtn.disabled = false;
    }
}

function updatePreviewButtonState(isPlaying) {
    const playBtn = document.getElementById('play-preview-btn');
    if (!playBtn) return;
    
    if (isPlaying) {
        playBtn.textContent = '⏹ Stop Preview';
        playBtn.classList.add('btn-preview-playing');
    } else {
        playBtn.textContent = '🔊 Play Preview';
        playBtn.classList.remove('btn-preview-playing');
    }
}

function setupKokoroMixer() {
    const modeSelector = document.getElementById('voice-mode-selector');
    const langSelect = document.getElementById('lang-code-select');
    const showAllCheckbox = document.getElementById('show-all-languages-checkbox');
    const addBtn = document.getElementById('add-to-blend-btn');
    const resetBtn = document.getElementById('formula-reset-btn');
    const previewBtn = document.getElementById('play-preview-btn');
    
    if (modeSelector) {
        modeSelector.querySelectorAll('.mode-pill').forEach(btn => {
            btn.addEventListener('click', () => {
                setVoiceMode(btn.getAttribute('data-mode'));
            });
        });
    }
    
    if (langSelect) {
        langSelect.addEventListener('change', () => {
            updateFilteredVoices();
        });
    }
    
    if (showAllCheckbox) {
        showAllCheckbox.addEventListener('change', () => {
            updateFilteredVoices();
        });
    }
    
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            addVoiceToBlend();
        });
    }
    
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            activeBlendVoices = [];
            renderBlendMixer();
            updateFilteredVoices();
            showToast('Mix reset successfully.', 'success');
        });
    }
    
    if (previewBtn) {
        previewBtn.addEventListener('click', () => {
            playVoicePreview();
        });
    }
    
    renderPresets();
}

