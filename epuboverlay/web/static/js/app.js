import { fetchConfig, fetchChapters, purgeAllCache } from './api.js';
import { showToast } from './utils.js';
import { startStatsPolling } from './stats.js';
import { setupKokoroMixer, updateFilteredVoices, setKokoroVoices, activeVoiceMode } from './kokoro.js';
import { refreshJobsList, connectSSE } from './jobs.js';
import { initSettings } from './settings.js';
import { showConfirmModal } from './modal.js';

// DOM References
const jobForm = document.getElementById('job-form');
const submitBtn = document.getElementById('submit-btn');
const epubFile = document.getElementById('epub-file');
const epubUploadZone = document.getElementById('epub-upload-zone');
const epubFileName = document.getElementById('epub-file-name');
const refAudioFile = document.getElementById('ref-audio-file');
const refAudioUploadZone = document.getElementById('ref-audio-upload-zone');
const refAudioFileName = document.getElementById('ref-audio-file-name');
const synthSelect = document.getElementById('synthesizer-select');

const extractForm = document.getElementById('extract-form');
const extractSubmitBtn = document.getElementById('extract-submit-btn');
const extractEpubFile = document.getElementById('extract-epub-file');
const extractEpubUploadZone = document.getElementById('extract-epub-upload-zone');
const extractEpubFileName = document.getElementById('extract-epub-file-name');
const extractStatus = document.getElementById('extract-status');
const extractStatusTitle = document.getElementById('extract-status-title');
const extractStatusBadge = document.getElementById('extract-status-badge');
const extractStatusMessage = document.getElementById('extract-status-message');

const tabGenerate = document.getElementById('tab-generate');
const tabExtract = document.getElementById('tab-extract');
const tabSettings = document.getElementById('tab-settings');
const modeGenerate = document.getElementById('mode-generate');
const modeExtract = document.getElementById('mode-extract');
const modeSettings = document.getElementById('mode-settings');

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Fetch config and setup defaults
    try {
        const config = await fetchConfig();
        setKokoroVoices(config.kokoro_voices || []);
        applyConfigDefaults(config.defaults || {});
    } catch (err) {
        showToast('Failed to fetch config: ' + err.message, 'error');
    }

    // 2. Setup systems
    setupTabs();
    setupFileUploads();
    setupSynthesizerToggle();
    setupChapterSelection();
    setupForm();
    setupExtractForm();
    setupKokoroMixer();
    
    // Initialize settings panel
    initSettings();

    // Start stats polling
    startStatsPolling();

    // Load initial jobs
    refreshJobsList(onJobUpdate);

    // Bind purge cache button
    const purgeBtn = document.getElementById('purge-cache-btn');
    if (purgeBtn) {
        purgeBtn.addEventListener('click', async () => {
            const confirmed1 = await showConfirmModal(
                "Purge All Cache",
                "Are you sure you want to clear all pipeline cache and jobs?",
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
                await purgeAllCache();
                showToast('All caches and non-running jobs purged.', 'success');
                refreshJobsList(onJobUpdate);
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    }
});

function applyConfigDefaults(defaults) {
    if (synthSelect) synthSelect.value = defaults.synthesizer || 'f5-tts';
    
    const deviceSelect = document.getElementById('device-select');
    if (deviceSelect) deviceSelect.value = defaults.device || '';

    const speedInput = document.getElementById('speed-input');
    if (speedInput) speedInput.value = defaults.speed || 1.0;

    const maxCharsInput = document.getElementById('max-chars-input');
    if (maxCharsInput) maxCharsInput.value = defaults.max_chars || 150;

    const concurrencyInput = document.getElementById('concurrency-input');
    if (concurrencyInput) concurrencyInput.value = defaults.concurrency || 2;

    const langSelect = document.getElementById('lang-code-select');
    if (langSelect) langSelect.value = defaults.lang_code || 'a';

    const voiceSelect = document.getElementById('voice-select');
    if (voiceSelect) voiceSelect.value = defaults.voice || 'af_heart';

    const formulaInput = document.getElementById('voice-formula-input');
    if (formulaInput) formulaInput.value = defaults.voice_formula || '';
    
    const nfeStepInput = document.getElementById('nfe-step-input');
    if (nfeStepInput) nfeStepInput.value = defaults.nfe_step || 32;

    const compileCheckbox = document.getElementById('compile-checkbox');
    if (compileCheckbox) compileCheckbox.checked = !!defaults.compile;
}

// Global SSE update callback
function onJobUpdate(job) {
    import('./jobs.js').then(module => {
        module.renderActiveJob(job, onJobUpdate);
    });
}

// Tab Switching
function setupTabs() {
    tabGenerate.addEventListener('click', () => {
        tabGenerate.classList.add('active');
        tabExtract.classList.remove('active');
        tabSettings.classList.remove('active');
        modeGenerate.style.display = 'block';
        modeExtract.style.display = 'none';
        modeSettings.style.display = 'none';
    });

    tabExtract.addEventListener('click', () => {
        tabExtract.classList.add('active');
        tabGenerate.classList.remove('active');
        tabSettings.classList.remove('active');
        modeExtract.style.display = 'block';
        modeGenerate.style.display = 'none';
        modeSettings.style.display = 'none';
    });

    tabSettings.addEventListener('click', () => {
        tabSettings.classList.add('active');
        tabGenerate.classList.remove('active');
        tabExtract.classList.remove('active');
        modeSettings.style.display = 'block';
        modeGenerate.style.display = 'none';
        modeExtract.style.display = 'none';
    });
}

// File Drop Zone Handling
function setupFileUploads() {
    setupDropZone(epubUploadZone, epubFile, epubFileName);
    setupDropZone(refAudioUploadZone, refAudioFile, refAudioFileName);
    setupDropZone(extractEpubUploadZone, extractEpubFile, extractEpubFileName);
}

function setupDropZone(zone, input, nameDisplay) {
    if (!zone || !input) return;
    
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
    if (!el) return;
    el.textContent = `📎 ${name}`;
    el.style.display = 'block';
}

// Synthesizer Type Toggling
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
            updateFilteredVoices();
        } else {
            cloningOptions.style.display = 'none';
            f5TtsOptions.style.display = 'none';
            kokoroOptions.style.display = 'none';
        }
    }

    synthSelect.addEventListener('change', toggleFields);
    toggleFields();
}

// Chapter Selection Loader
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

        try {
            const chapters = await fetchChapters(file);
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

// Form Submission for Job
function setupForm() {
    jobForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(jobForm);

        // Adjust Kokoro parameters based on active voice mode
        if (synthSelect.value === 'kokoro') {
            const currentMode = document.getElementById('voice-mode-selector').querySelector('.mode-pill.active').getAttribute('data-mode');
            if (currentMode === 'single') {
                const vs = document.getElementById('voice-select');
                formData.set('voice', vs ? vs.value : '');
                formData.set('voice_formula', '');
            } else {
                formData.set('voice', '');
                const vfi = document.getElementById('voice-formula-input');
                formData.set('voice_formula', vfi ? vfi.value : '');
            }
        }

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
            
            document.getElementById('chapter-selection-panel').style.display = 'none';
            document.getElementById('chapters-list-wrapper').innerHTML = '';

            // Reset dynamic fields
            const cloningOptions = document.getElementById('cloning-options');
            const f5TtsOptions = document.getElementById('f5-tts-options');
            const kokoroOptions = document.getElementById('kokoro-options');
            cloningOptions.style.display = 'block';
            f5TtsOptions.style.display = 'block';
            kokoroOptions.style.display = 'none';

            // Refresh list & launch SSE
            refreshJobsList(onJobUpdate);
            connectSSE(job.id, onJobUpdate);

        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '🚀 Start Generation';
        }
    });
}

// Extraction Form Submission
function setupExtractForm() {
    extractForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!extractEpubFile.files.length) {
            showToast('Please select an EPUB file.', 'error');
            return;
        }

        extractSubmitBtn.disabled = true;
        extractSubmitBtn.innerHTML = '<span class="spinner"></span> Extracting...';

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

            extractStatusTitle.textContent = 'Extraction Complete!';
            extractStatusBadge.className = 'phase-badge done';
            extractStatusBadge.innerHTML = '<span class="phase-text">Done</span>';
            extractStatusMessage.textContent = `✓ Downloaded ${filename}`;

            showToast('Audio + LRC extracted successfully!', 'success');
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
