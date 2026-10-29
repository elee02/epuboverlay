import { fetchConfig, fetchChapters, purgeAllCache, fetchReferences } from './api.js?v=8';
import {
    showToast,
    escapeHtml,
    setInstalledSynthesizers,
    applyInstalledSynthesizersToSelect,
    getPreferredInstalledSynthesizer,
    setupExportCheckboxDependencies,
    SCENARIO_PROFILES,
} from './utils.js?v=8';
import { startStatsPolling } from './stats.js?v=8';
import { setupKokoroMixer, updateFilteredVoices, setKokoroVoices } from './kokoro.js?v=8';
import { refreshJobsList, connectSSE } from './jobs.js?v=8';
import { initSettings } from './settings.js?v=8';
import { showConfirmModal } from './modal.js?v=8';
import { initPlayground } from './playground.js?v=8';
import { setupPocketModeToggle, setPocketVoices } from './pocket.js?v=8';
import { savedReferences, loadSavedReferencesGlobal, populateReferencesDropdowns } from './references.js?v=8';
export { savedReferences, loadSavedReferencesGlobal, populateReferencesDropdowns };


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
const extractAudioFormat = document.getElementById('extract-audio-format');
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
        setInstalledSynthesizers(config.installed_synthesizers || {});
        applyInstalledSynthesizersToSelect(synthSelect);
        applyInstalledSynthesizersToSelect(document.getElementById('default-synthesizer'));
        setKokoroVoices(config.kokoro_voices || []);
        setPocketVoices(config.pocket_voices || []);
        populatePresetSpeakerSelects(config.qwen3_voices || []);
        applyConfigDefaults(config.defaults || {});
    } catch (err) {
        showToast('Failed to fetch config: ' + err.message, 'error');
    }

    // Load saved reference voices
    await loadSavedReferencesGlobal();

    // 2. Setup systems
    setupSidebarNav();
    setupFileUploads();
    setupSynthesizerToggle();
    setupChapterSelection();
    setupForm();
    setupExtractForm();
    setupKokoroMixer();
    setupPocketFormPanel();
    setupGenerateRefSelectors();
    setupScenarioAndDirectorControls();

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
            const confirmed = await showConfirmModal(
                "Purge All Cache",
                "This will permanently delete all cached chapter audio/SMIL data and all non-running jobs. Are you sure you want to continue?",
                "Yes, Purge Everything",
                "btn-danger"
            );
            if (!confirmed) return;

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

function populatePresetSpeakerSelects(qwenVoices) {
    if (Array.isArray(qwenVoices) && qwenVoices.length > 0) {
        ['qwen-speaker-select', 'pg-qwen-speaker-select'].forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const prev = sel.value;
            sel.innerHTML = '';
            qwenVoices.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.id;
                opt.textContent = v.name;
                sel.appendChild(opt);
            });
            if (prev && qwenVoices.some(v => v.id === prev)) {
                sel.value = prev;
            }
        });
    }
}

function applyConfigDefaults(defaults) {
    if (synthSelect) {
        synthSelect.value = defaults.synthesizer || getPreferredInstalledSynthesizer('dummy');
        applyInstalledSynthesizersToSelect(synthSelect);
    }

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

    const qwenSpeakerSelect = document.getElementById('qwen-speaker-select');
    if (qwenSpeakerSelect && defaults.qwen_speaker) {
        qwenSpeakerSelect.value = defaults.qwen_speaker;
    }
}

// ── Global SSE update callback ──────────────────────────────────────────────

function onJobUpdate(job) {
    import('./jobs.js?v=8').then(module => {
        module.renderActiveJob(job, onJobUpdate);
    });
}

// ── Sidebar Navigation ──────────────────────────────────────────────────────

function setupSidebarNav() {
    const pages = {
        generate: document.getElementById('page-generate'),
        playground: document.getElementById('page-playground'),
        extract: document.getElementById('page-extract'),
        settings: document.getElementById('page-settings'),
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
    const refTextLabel = document.getElementById('ref-text-label');
    const f5TtsOptions = document.getElementById('f5-tts-options');
    const kokoroOptions = document.getElementById('kokoro-options');
    const pocketOptions = document.getElementById('pocket-tts-options');
    const qwenOptions = document.getElementById('qwen3-tts-options');
    const emotionDirector = document.getElementById('emotion-director-options');

    const qwenVoiceModeSelector = document.getElementById('qwen-voice-mode-selector');
    const qwenModeSelect = document.getElementById('qwen-mode-select');
    const qwenModelSelect = document.getElementById('qwen-model-select');
    const qwenSpeakerGroup = document.getElementById('qwen-speaker-group');

    function syncQwenModelAndPills(modeVal) {
        if (qwenVoiceModeSelector) {
            qwenVoiceModeSelector.querySelectorAll('.mode-pill').forEach(p => {
                p.classList.toggle('active', p.getAttribute('data-mode') === modeVal);
            });
        }
        if (qwenModeSelect && qwenModeSelect.value !== modeVal) {
            qwenModeSelect.value = modeVal;
        }
        if (qwenModelSelect) {
            if (modeVal === 'voice_design') {
                qwenModelSelect.value = 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign';
            } else if (modeVal === 'clone' && !qwenModelSelect.value.includes('Base')) {
                qwenModelSelect.value = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base';
            } else if (modeVal === 'custom_voice') {
                qwenModelSelect.value = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice';
            }
        }
    }

    function toggleFields() {
        const val = synthSelect.value;
        const qwenMode = qwenModeSelect ? qwenModeSelect.value : 'custom_voice';

        if (qwenSpeakerGroup) {
            qwenSpeakerGroup.style.display = qwenMode === 'custom_voice' ? 'flex' : 'none';
        }

        const needsRefAudio =
            val === 'f5-tts' ||
            (val === 'qwen3-tts' && qwenMode === 'clone');

        if (cloningOptions) cloningOptions.style.display = needsRefAudio ? 'grid' : 'none';
        if (refTextLabel) {
            refTextLabel.textContent = val === 'f5-tts'
                ? 'Reference Text (Required — Exact Transcript of Reference Audio)'
                : 'Reference Text (Optional — Transcript Improves Voice Cloning Accuracy)';
        }
        if (f5TtsOptions) f5TtsOptions.style.display = val === 'f5-tts' ? 'block' : 'none';
        if (kokoroOptions) kokoroOptions.style.display = val === 'kokoro' ? 'block' : 'none';
        if (pocketOptions) pocketOptions.style.display = val === 'pocket-tts' ? 'block' : 'none';
        if (qwenOptions) qwenOptions.style.display = val === 'qwen3-tts' ? 'block' : 'none';
        if (emotionDirector) {
            emotionDirector.style.display = (val === 'qwen3-tts') ? 'block' : 'none';
        }

        if (val === 'kokoro') updateFilteredVoices();
    }

    if (qwenVoiceModeSelector) {
        qwenVoiceModeSelector.querySelectorAll('.mode-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                const m = pill.getAttribute('data-mode') || 'custom_voice';
                syncQwenModelAndPills(m);
                toggleFields();
            });
        });
    }

    if (qwenModeSelect) {
        qwenModeSelect.addEventListener('change', () => {
            syncQwenModelAndPills(qwenModeSelect.value);
            toggleFields();
        });
    }

    synthSelect.addEventListener('change', toggleFields);
    toggleFields();
}

// ── PocketTTS form panel ────────────────────────────────────────────────────

function setupPocketFormPanel() {
    setupPocketModeToggle({
        modeSelector: document.getElementById('pocket-voice-mode-selector'),
        presetPanel: document.getElementById('pocket-preset-panel'),
        clonePanel: document.getElementById('pocket-clone-panel'),
        voiceSelect: document.getElementById('pocket-voice-select'),
        dialogueVoiceSelect: document.getElementById('pocket-dialogue-voice-select'),
    });
}

// ── Scenario Director & Emotion Chips ───────────────────────────────────────

function setupScenarioAndDirectorControls() {
    const genGrid = document.getElementById('generate-scenario-grid');
    const scenarioInput = document.getElementById('scenario-input');
    if (genGrid) {
        genGrid.querySelectorAll('.scenario-card').forEach(card => {
            card.addEventListener('click', () => {
                const key = card.getAttribute('data-scenario') || 'custom';
                genGrid.querySelectorAll('.scenario-card').forEach(c => c.classList.toggle('active', c === card));
                if (scenarioInput) scenarioInput.value = key;
                const prof = SCENARIO_PROFILES[key];
                if (!prof) return;

                const speedEl = document.getElementById('speed-input');
                const maxCharsEl = document.getElementById('max-chars-input');
                const tempEl = document.getElementById('pocket-temp-input');
                const lsdEl = document.getElementById('pocket-lsd-input');
                const clampEl = document.getElementById('pocket-noise-clamp-input');
                const eosEl = document.getElementById('pocket-eos-input');
                const framesEl = document.getElementById('pocket-frames-eos-input');
                const instructEl = document.getElementById('instruct-input');

                if (speedEl) speedEl.value = prof.speed;
                if (maxCharsEl) maxCharsEl.value = prof.max_chars;
                if (tempEl) tempEl.value = prof.temp;
                if (lsdEl) lsdEl.value = prof.lsd_decode_steps;
                if (clampEl) clampEl.value = prof.noise_clamp !== undefined ? prof.noise_clamp : '';
                if (eosEl) eosEl.value = prof.eos_threshold;
                if (framesEl) framesEl.value = prof.frames_after_eos !== undefined ? prof.frames_after_eos : '';
                if (instructEl && prof.instruct !== undefined) instructEl.value = prof.instruct;

                showToast(`Scenario "${prof.label}" applied.`, 'info');
            });
        });
    }

    // Wire all .instruct-chip-bar containers across both Generate & Playground pages
    document.querySelectorAll('.instruct-chip-bar').forEach(bar => {
        const targetId = bar.getAttribute('data-target');
        const inputEl = targetId ? document.getElementById(targetId) : null;
        if (!inputEl) return;
        bar.querySelectorAll('.instruct-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                inputEl.value = chip.getAttribute('data-prompt') || '';
                inputEl.focus();
            });
        });
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
            wrapper.innerHTML = `<div class="error-chapters" style="padding: 1rem; color: var(--danger); text-align: center;">✗ Error loading chapters: ${escapeHtml(err.message)}</div>`;
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
                    <input type="checkbox" class="chapter-checkbox" data-idref="${escapeHtml(ch.idref)}" ${checkedAttr} style="width: auto; margin: 0; cursor: pointer;">
                    <span class="chapter-title" style="font-weight: 500; font-size: 0.9rem;">${escapeHtml(ch.title)}</span>
                </label>
                <span class="chapter-char-count" style="font-size: 0.8rem; color: var(--text-secondary); white-space: nowrap;">${Number(ch.char_count) || 0} chars</span>
                <button type="button" class="btn btn-xs btn-ghost toggle-preview-btn" style="white-space: nowrap; font-size: 0.8rem; padding: 0.2rem 0.5rem; line-height: 1.2;">Show Preview</button>
            </div>
            <div class="chapter-preview-container hidden" style="padding: 0.75rem; background: var(--bg-secondary); border-radius: 4px; margin-top: 0.25rem;">
                <pre class="chapter-preview-text" style="margin: 0; font-family: inherit; font-size: 0.8rem; white-space: pre-wrap; word-break: break-all; color: var(--text-secondary); max-height: 200px; overflow-y: auto;">${escapeHtml(ch.preview || 'No text preview available.')}</pre>
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
        formData.delete('ref_id');

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
                const pocketRefVoiceSelect = document.getElementById('pocket-ref-voice-select');
                if (pocketRefVoiceSelect && pocketRefVoiceSelect.value) {
                    formData.set('ref_id', pocketRefVoiceSelect.value);
                } else {
                    const pocketRefAudio = document.getElementById('pocket-ref-audio-file');
                    if (pocketRefAudio && pocketRefAudio.files.length > 0) {
                        formData.set('ref_audio', pocketRefAudio.files[0]);
                    }
                }
            }
        } else if (synthSelect.value === 'f5-tts' || synthSelect.value === 'qwen3-tts') {
            formData.set('voice', '');
            formData.set('voice_formula', '');
            formData.set('pocket_voice', '');

            const qwenMode = document.getElementById('qwen-mode-select')?.value || 'custom_voice';
            const shouldAttachCloneRef =
                synthSelect.value === 'f5-tts' ||
                (synthSelect.value === 'qwen3-tts' && qwenMode === 'clone');

            if (shouldAttachCloneRef) {
                const refVoiceSelect = document.getElementById('ref-voice-select');
                if (refVoiceSelect && refVoiceSelect.value) {
                    formData.set('ref_id', refVoiceSelect.value);
                } else {
                    const refAudioFile = document.getElementById('ref-audio-file');
                    if (refAudioFile && refAudioFile.files.length > 0) {
                        formData.set('ref_audio', refAudioFile.files[0]);
                    }
                }
            } else {
                formData.set('ref_text', '');
            }
        } else {
            // dummy or any other
            formData.set('voice', '');
            formData.set('voice_formula', '');
            formData.set('pocket_voice', '');
            formData.set('ref_text', '');
        }

        if (!epubFile.files.length) {
            showToast('Please select an e-book or document file.', 'error');
            return;
        }

        const selectedSynth = synthSelect.value;
        if (selectedSynth === 'f5-tts') {
            const hasSavedRef = formData.get('ref_id');
            const refAudioFile = document.getElementById('ref-audio-file');
            if (!hasSavedRef && (!refAudioFile || !refAudioFile.files.length)) {
                showToast('Reference audio is required for F5-TTS.', 'error');
                return;
            }
            if (!hasSavedRef && !formData.get('ref_text')?.trim()) {
                showToast('Reference text is required for F5-TTS.', 'error');
                return;
            }
        } else if (selectedSynth === 'qwen3-tts') {
            const qwenMode = document.getElementById('qwen-mode-select')?.value || 'custom_voice';
            if (qwenMode === 'clone') {
                const hasSavedRef = formData.get('ref_id');
                const refAudioFile = document.getElementById('ref-audio-file');
                if (!hasSavedRef && (!refAudioFile || !refAudioFile.files.length)) {
                    showToast('Reference audio is required for Qwen3-TTS clone mode.', 'error');
                    return;
                }
            } else if (qwenMode === 'voice_design' && !formData.get('instruct')?.trim()) {
                showToast('Please enter an Emotion & Intonation Director prompt to design a voice.', 'error');
                return;
            }
        } else if (selectedSynth === 'pocket-tts') {
            const activePocketMode = document.getElementById('pocket-voice-mode-selector')
                .querySelector('.mode-pill.active').getAttribute('data-mode');
            if (activePocketMode === 'clone') {
                const hasSavedRef = formData.get('ref_id');
                const pocketRefAudio = document.getElementById('pocket-ref-audio-file');
                if (!hasSavedRef && (!pocketRefAudio || !pocketRefAudio.files.length)) {
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

            // Re-sync dynamic fields for current synthesizer
            synthSelect.dispatchEvent(new Event('change'));

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
    setupExportCheckboxDependencies({
        audioFmtSelect: extractAudioFormat,
        mp4Cb: extractMp4Checkbox,
        mp4Group: extractMp4Checkbox ? extractMp4Checkbox.closest('label') : null,
        embedSubsCb: extractEmbedSubsCheckbox,
        embedSubsGroup: extractEmbedSubsGroup,
        fmtAss: document.getElementById('extract-fmt-ass'),
        fmtSrt: document.getElementById('extract-fmt-srt'),
        fmtVtt: document.getElementById('extract-fmt-vtt'),
        fmtTtml: document.getElementById('extract-fmt-ttml'),
        fmtSbv: document.getElementById('extract-fmt-sbv'),
        fmtLrc: document.getElementById('extract-fmt-lrc'),
        fmtTxt: document.getElementById('extract-fmt-txt'),
        mergeCb: document.getElementById('extract-merge-checkbox'),
        centerCb: document.getElementById('extract-center-checkbox'),
        submitBtn: extractSubmitBtn,
        coverInput: extractCoverFile,
        coverContainer: extractCoverUploadZone,
        coverNameEl: extractCoverFileName,
    });

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

        const audioFormatVal = extractAudioFormat.value;
        const includeAudio = audioFormatVal !== 'none';

        if (formats.length === 0 && !includeAudio) {
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
        formData.append('include_audio', includeAudio ? 'true' : 'false');
        formData.append('audio_format', includeAudio ? audioFormatVal : 'm4b');

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

function setupGenerateRefSelectors() {
    const f5VoiceSelect = document.getElementById('ref-voice-select');
    const f5UploadGroup = document.getElementById('generate-f5-upload-group');
    const f5RefTextGroup = document.getElementById('generate-f5-ref-text-group');
    const f5RefTextInput = document.getElementById('ref-text-input');

    if (f5VoiceSelect && f5UploadGroup) {
        f5VoiceSelect.addEventListener('change', () => {
            const val = f5VoiceSelect.value;
            if (val) {
                f5UploadGroup.style.display = 'none';
                // Find saved voice transcript text
                const ref = savedReferences.find(r => r.id === val);
                if (ref) {
                    f5RefTextInput.value = ref.text || '';
                    f5RefTextInput.readOnly = true;
                    f5RefTextInput.style.background = 'var(--bg-secondary)';
                }
            } else {
                f5UploadGroup.style.display = 'block';
                f5RefTextInput.value = '';
                f5RefTextInput.readOnly = false;
                f5RefTextInput.style.background = '';
            }
        });
    }

    const pocketVoiceSelect = document.getElementById('pocket-ref-voice-select');
    const pocketUploadGroup = document.getElementById('generate-pocket-upload-group');

    if (pocketVoiceSelect && pocketUploadGroup) {
        pocketVoiceSelect.addEventListener('change', () => {
            if (pocketVoiceSelect.value) {
                pocketUploadGroup.style.display = 'none';
            } else {
                pocketUploadGroup.style.display = 'block';
            }
        });
    }
}

