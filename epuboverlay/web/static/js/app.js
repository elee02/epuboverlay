import { fetchConfig, fetchChapters, purgeAllCache } from './api.js';
import { showToast } from './utils.js';
import { startStatsPolling } from './stats.js';
import { setupKokoroMixer, updateFilteredVoices, setKokoroVoices } from './kokoro.js';
import { refreshJobsList, connectSSE } from './jobs.js';
import { initSettings } from './settings.js';
import { showConfirmModal } from './modal.js';
import { initPlayground } from './playground.js';
import { setupPocketModeToggle, setPocketVoices } from './pocket.js';

// ── DOM References ──────────────────────────────────────────────────────────

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
const extractCoverFile = document.getElementById('extract-cover-file');
const extractCoverUploadZone = document.getElementById('extract-cover-upload-zone');
const extractCoverFileName = document.getElementById('extract-cover-file-name');
const extractAudioCheckbox = document.getElementById('extract-audio-checkbox');
const extractMp4Checkbox = document.getElementById('extract-mp4-checkbox');
const extractEmbedSubsCheckbox = document.getElementById('extract-embed-subs-checkbox');
const extractEmbedSubsGroup = document.getElementById('extract-embed-subs-group');
const extractStatus = document.getElementById('extract-status');
const extractStatusTitle = document.getElementById('extract-status-title');
const extractStatusBadge = document.getElementById('extract-status-badge');
const extractStatusMessage = document.getElementById('extract-status-message');

// ── Bootstrap ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Fetch config and setup defaults
    try {
        const config = await fetchConfig();
        setKokoroVoices(config.kokoro_voices || []);
        setPocketVoices(config.pocket_voices || []);
        applyConfigDefaults(config.defaults || {});
    } catch (err) {
        showToast('Failed to fetch config: ' + err.message, 'error');
    }

    // 2. Setup systems
    setupSidebarNav();
    setupFileUploads();
    setupSynthesizerToggle();
    setupChapterSelection();
    setupForm();
    setupExtractForm();
    setupKokoroMixer();
    setupPocketFormPanel();

    // Voice Playground
    initPlayground();

    // Settings panel
    initSettings();

    // Stats polling
    startStatsPolling();

    // Load initial jobs
    refreshJobsList(onJobUpdate);

    // Purge cache button
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

// ── Config defaults ─────────────────────────────────────────────────────────

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

    const pocketVoiceSelect = document.getElementById('pocket-voice-select');
    if (pocketVoiceSelect) pocketVoiceSelect.value = defaults.pocket_voice || 'alba';
}

// ── Global SSE update callback ──────────────────────────────────────────────

function onJobUpdate(job) {
    import('./jobs.js').then(module => {
        module.renderActiveJob(job, onJobUpdate);
    });
}

// ── Sidebar Navigation ──────────────────────────────────────────────────────

function setupSidebarNav() {
    const pages = {
        generate:   document.getElementById('page-generate'),
        playground: document.getElementById('page-playground'),
        extract:    document.getElementById('page-extract'),
        settings:   document.getElementById('page-settings'),
    };

    const navItems = document.querySelectorAll('.nav-item[data-page]');

    function showPage(pageId) {
        Object.entries(pages).forEach(([id, el]) => {
            if (el) el.style.display = id === pageId ? 'block' : 'none';
        });
        navItems.forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-page') === pageId);
        });
    }

    navItems.forEach(btn => {
        btn.addEventListener('click', () => showPage(btn.getAttribute('data-page')));
    });

    // Default: generate
    showPage('generate');
}

// ── File Upload Zones ───────────────────────────────────────────────────────

function setupFileUploads() {
    setupDropZone(epubUploadZone, epubFile, epubFileName);
    setupDropZone(refAudioUploadZone, refAudioFile, refAudioFileName);
    setupDropZone(extractEpubUploadZone, extractEpubFile, extractEpubFileName);
    setupDropZone(extractCoverUploadZone, extractCoverFile, extractCoverFileName);

    // PocketTTS clone upload zone in the form
    const pocketZone = document.getElementById('pocket-ref-audio-upload-zone');
    const pocketInput = document.getElementById('pocket-ref-audio-file');
    const pocketName = document.getElementById('pocket-ref-audio-file-name');
    setupDropZone(pocketZone, pocketInput, pocketName);
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

// ── Synthesizer Type Toggling (Generate form) ───────────────────────────────

function setupSynthesizerToggle() {
    const cloningOptions = document.getElementById('cloning-options');
    const f5TtsOptions = document.getElementById('f5-tts-options');
    const kokoroOptions = document.getElementById('kokoro-options');
    const pocketOptions = document.getElementById('pocket-tts-options');

    function toggleFields() {
        const val = synthSelect.value;
        cloningOptions.style.display = val === 'f5-tts' ? 'grid' : 'none';
        f5TtsOptions.style.display   = val === 'f5-tts' ? 'block' : 'none';
        kokoroOptions.style.display  = val === 'kokoro'  ? 'block' : 'none';
        pocketOptions.style.display  = val === 'pocket-tts' ? 'block' : 'none';

        if (val === 'kokoro') updateFilteredVoices();
    }

    synthSelect.addEventListener('change', toggleFields);
    toggleFields();
}

// ── PocketTTS form panel ────────────────────────────────────────────────────

function setupPocketFormPanel() {
    setupPocketModeToggle({
        modeSelector: document.getElementById('pocket-voice-mode-selector'),
        presetPanel:  document.getElementById('pocket-preset-panel'),
        clonePanel:   document.getElementById('pocket-clone-panel'),
        voiceSelect:  document.getElementById('pocket-voice-select'),
    });
}

// ── Chapter Selection Loader ────────────────────────────────────────────────

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

// ── Form Submission for Job ──────────────────────────────────────────────────

function setupForm() {
    jobForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(jobForm);

        // Adjust parameters based on active synthesizer and clear unrelated fields
        formData.delete('ref_audio');

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
            formData.set('pocket_voice', '');
            formData.set('ref_text', '');
        } else if (synthSelect.value === 'pocket-tts') {
            formData.set('voice', '');
            formData.set('voice_formula', '');
            formData.set('ref_text', '');

            const activePocketMode = document.getElementById('pocket-voice-mode-selector')
                .querySelector('.mode-pill.active').getAttribute('data-mode');
            if (activePocketMode === 'preset') {
                const pocketVoiceSelect = document.getElementById('pocket-voice-select');
                formData.set('pocket_voice', pocketVoiceSelect ? pocketVoiceSelect.value : '');
            } else {
                formData.set('pocket_voice', '');
                const pocketRefAudio = document.getElementById('pocket-ref-audio-file');
                if (pocketRefAudio && pocketRefAudio.files.length > 0) {
                    formData.set('ref_audio', pocketRefAudio.files[0]);
                }
            }
        } else if (synthSelect.value === 'f5-tts') {
            formData.set('voice', '');
            formData.set('voice_formula', '');
            formData.set('pocket_voice', '');

            const refAudioFile = document.getElementById('ref-audio-file');
            if (refAudioFile && refAudioFile.files.length > 0) {
                formData.set('ref_audio', refAudioFile.files[0]);
            }
        } else {
            // dummy or any other
            formData.set('voice', '');
            formData.set('voice_formula', '');
            formData.set('pocket_voice', '');
            formData.set('ref_text', '');
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
            const activePocketMode = document.getElementById('pocket-voice-mode-selector')
                .querySelector('.mode-pill.active').getAttribute('data-mode');
            if (activePocketMode === 'clone') {
                const pocketRefAudio = document.getElementById('pocket-ref-audio-file');
                if (!pocketRefAudio || !pocketRefAudio.files.length) {
                    showToast('Reference audio is required for PocketTTS clone mode.', 'error');
                    return;
                }
            } else {
                const pocketVoiceSelect = document.getElementById('pocket-voice-select');
                if (!pocketVoiceSelect || !pocketVoiceSelect.value) {
                    showToast('Please select a PocketTTS preset voice.', 'error');
                    return;
                }
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
            const pocketOptions = document.getElementById('pocket-tts-options');
            if (cloningOptions) cloningOptions.style.display = 'none';
            if (f5TtsOptions) f5TtsOptions.style.display = 'none';
            if (kokoroOptions) kokoroOptions.style.display = 'none';
            if (pocketOptions) pocketOptions.style.display = 'none';

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

// ── Extraction Form Submission ──────────────────────────────────────────────

function setupExtractForm() {
    function updateCheckboxDependencies() {
        const audioChecked = extractAudioCheckbox.checked;
        const mp4Checked = extractMp4Checkbox.checked;
        const embedSubsChecked = extractEmbedSubsCheckbox.checked;
        const mp4Label = extractMp4Checkbox.closest('label');
        
        if (audioChecked) {
            extractMp4Checkbox.disabled = false;
            if (mp4Label) mp4Label.style.opacity = '1';
            
            extractEmbedSubsCheckbox.disabled = !mp4Checked;
            extractEmbedSubsGroup.style.opacity = mp4Checked ? '1' : '0.5';
            if (!mp4Checked) extractEmbedSubsCheckbox.checked = false;
        } else {
            extractMp4Checkbox.disabled = true;
            extractMp4Checkbox.checked = false;
            if (mp4Label) mp4Label.style.opacity = '0.5';
            
            extractEmbedSubsCheckbox.disabled = true;
            extractEmbedSubsCheckbox.checked = false;
            extractEmbedSubsGroup.style.opacity = '0.5';
        }

        const isMp4 = extractMp4Checkbox.checked;
        const isEmbed = extractEmbedSubsCheckbox.checked;

        const fmtAss = document.getElementById('extract-fmt-ass');
        const fmtSrt = document.getElementById('extract-fmt-srt');
        const fmtVtt = document.getElementById('extract-fmt-vtt');
        const fmtTtml = document.getElementById('extract-fmt-ttml');
        const fmtSbv = document.getElementById('extract-fmt-sbv');
        const fmtLrc = document.getElementById('extract-fmt-lrc');
        const fmtTxt = document.getElementById('extract-fmt-txt');

        function setFmtState(el, enabled) {
            if (!el) return;
            el.disabled = !enabled;
            const parentLabel = el.closest('label');
            if (parentLabel) {
                parentLabel.style.opacity = enabled ? '1' : '0.5';
            }
            if (!enabled) {
                el.checked = false;
            }
        }

        setFmtState(fmtTxt, true);

        if (isMp4) {
            setFmtState(fmtAss, true);
            setFmtState(fmtSrt, true);
            setFmtState(fmtVtt, true);
            setFmtState(fmtTtml, true);
            setFmtState(fmtSbv, true);
            setFmtState(fmtLrc, false);
        } else {
            setFmtState(fmtAss, false);
            setFmtState(fmtSrt, false);
            setFmtState(fmtVtt, false);
            setFmtState(fmtTtml, false);
            setFmtState(fmtSbv, false);
            setFmtState(fmtLrc, true);
        }

        const anyFmtChecked = [fmtAss, fmtSrt, fmtVtt, fmtTtml, fmtSbv, fmtLrc, fmtTxt].some(el => el && el.checked);
        const audioOrAnyFmtSelected = audioChecked || anyFmtChecked;

        const mergeCb = document.getElementById('extract-merge-checkbox');
        if (mergeCb) {
            mergeCb.disabled = !audioOrAnyFmtSelected;
            const mergeLabel = mergeCb.closest('label');
            if (mergeLabel) {
                mergeLabel.style.opacity = audioOrAnyFmtSelected ? '1' : '0.5';
            }
            if (!audioOrAnyFmtSelected) {
                mergeCb.checked = false;
            }
        }

        const centerApplicableChecked = isEmbed || [fmtAss, fmtSrt, fmtVtt, fmtTtml, fmtSbv].some(el => el && el.checked && !el.disabled);
        const centerCb = document.getElementById('extract-center-checkbox');
        if (centerCb) {
            centerCb.disabled = !centerApplicableChecked;
            const centerLabel = centerCb.closest('label');
            if (centerLabel) {
                centerLabel.style.opacity = centerApplicableChecked ? '1' : '0.5';
            }
            if (!centerApplicableChecked) {
                centerCb.checked = false;
            }
        }

        if (extractSubmitBtn) {
            extractSubmitBtn.disabled = !audioOrAnyFmtSelected;
        }
    }

    if (extractAudioCheckbox && extractMp4Checkbox) {
        extractAudioCheckbox.addEventListener('change', updateCheckboxDependencies);
        extractMp4Checkbox.addEventListener('change', updateCheckboxDependencies);
        if (extractEmbedSubsCheckbox) {
            extractEmbedSubsCheckbox.addEventListener('change', () => {
                if (extractEmbedSubsCheckbox.checked) {
                    const centerCb = document.getElementById('extract-center-checkbox');
                    if (centerCb) centerCb.checked = true;
                }
                updateCheckboxDependencies();
            });
        }
        ['ass', 'srt', 'vtt', 'ttml', 'sbv', 'lrc', 'txt'].forEach(fmt => {
            const el = document.getElementById(`extract-fmt-${fmt}`);
            if (el) {
                el.addEventListener('change', updateCheckboxDependencies);
            }
        });
        updateCheckboxDependencies();
    }

    extractForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!extractEpubFile.files.length) {
            showToast('Please select an EPUB file.', 'error');
            return;
        }

        extractSubmitBtn.disabled = true;
        extractSubmitBtn.innerHTML = '<span class="spinner"></span> Exporting...';

        extractStatus.style.display = 'block';
        extractStatusTitle.textContent = 'Exporting Audiobook + Subtitles...';
        extractStatusBadge.className = 'phase-badge synthesizing';
        extractStatusBadge.querySelector('.phase-text').textContent = 'Processing';
        extractStatusMessage.textContent = 'Uploading and processing EPUB file...';
        extractStatusMessage.style.display = 'block';

        const formats = [];
        ['ass', 'srt', 'vtt', 'ttml', 'sbv', 'lrc', 'txt'].forEach(fmt => {
            const el = document.getElementById(`extract-fmt-${fmt}`);
            if (el && el.checked) {
                formats.push(fmt);
            }
        });

        if (formats.length === 0 && !extractAudioCheckbox.checked) {
            showToast('Please select at least one format (Audiobook or a subtitle format) to export.', 'error');
            extractSubmitBtn.disabled = false;
            extractSubmitBtn.innerHTML = 'Export';
            extractStatus.style.display = 'none';
            return;
        }

        const formData = new FormData();
        formData.append('epub', extractEpubFile.files[0]);
        formData.append('merge', document.getElementById('extract-merge-checkbox').checked);
        formData.append('formats', formats.length > 0 ? formats.join(',') : 'none');
        formData.append('center', document.getElementById('extract-center-checkbox').checked ? 'true' : 'false');
        formData.append('mp4_video', extractMp4Checkbox.checked ? 'true' : 'false');
        formData.append('embed_subtitles', extractEmbedSubsCheckbox.checked ? 'true' : 'false');
        formData.append('include_audio', extractAudioCheckbox.checked ? 'true' : 'false');
        
        if (extractCoverFile && extractCoverFile.files.length > 0) {
            formData.append('cover_art', extractCoverFile.files[0]);
        }

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
            const filename = extractEpubFile.files[0].name.replace('.epub', '') + '_audiobook_subtitles.zip';

            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

            extractStatusTitle.textContent = 'Export Complete!';
            extractStatusBadge.className = 'phase-badge done';
            extractStatusBadge.innerHTML = '<span class="phase-text">Done</span>';
            extractStatusMessage.textContent = `✓ Downloaded ${filename}`;

            showToast('Audiobook + Subtitles exported successfully!', 'success');
            extractForm.reset();
            extractEpubFileName.style.display = 'none';
            if (extractCoverFileName) extractCoverFileName.style.display = 'none';
            updateCheckboxDependencies();

        } catch (err) {
            extractStatusTitle.textContent = 'Export Failed';
            extractStatusBadge.className = 'phase-badge error';
            extractStatusBadge.innerHTML = '<span class="phase-text">Error</span>';
            extractStatusMessage.textContent = `✗ ${err.message}`;
            showToast(err.message, 'error');
        } finally {
            extractSubmitBtn.disabled = false;
            extractSubmitBtn.innerHTML = 'Export';
        }
    });
}
