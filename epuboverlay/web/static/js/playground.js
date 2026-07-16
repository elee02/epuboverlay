/**
 * playground.js — Voice Playground page controller.
 *
 * Manages synthesizer switching, voice configuration, synthesis requests,
 * and audio playback in the Voice Playground tab.
 */

import { previewVoice } from './api.js';
import { showToast } from './utils.js';
import {
    setupKokoroMixer,
    updateFilteredVoices,
    setVoiceMode,
    renderPresets,
    activeVoiceMode as kokoroVoiceMode,
    activeBlendVoices,
} from './kokoro.js';
import {
    setupPocketModeToggle,
    getPocketVoiceParams,
    populatePocketVoiceSelect,
} from './pocket.js';

let pgAudio = null;
let pgSynthStart = 0;

// ── Playground DOM element references ──────────────────────────────────────

function getElements() {
    return {
        // Synthesizer selector
        synthSelector:      document.getElementById('pg-synth-selector'),
        // Panels
        kokoroPanel:        document.getElementById('pg-kokoro-panel'),
        pocketPanel:        document.getElementById('pg-pocket-panel'),
        f5Panel:            document.getElementById('pg-f5-panel'),
        // Kokoro sub-elements (prefixed pg- to avoid collision with form)
        voiceModeSelector:  document.getElementById('pg-voice-mode-selector'),
        langSelect:         document.getElementById('pg-lang-code-select'),
        voiceSelect:        document.getElementById('pg-voice-select'),
        blendVisualizerBar: document.getElementById('pg-blend-visualizer-bar'),
        blendChannelsList:  document.getElementById('pg-blend-channels-list'),
        voiceFormulaInput:  document.getElementById('pg-voice-formula-input'),
        blendAddSelect:     document.getElementById('pg-blend-add-select'),
        addToBlendBtn:      document.getElementById('pg-add-to-blend-btn'),
        formulaResetBtn:    document.getElementById('pg-formula-reset-btn'),
        blendPresetsGrid:   document.getElementById('pg-blend-presets-grid'),
        showAllCheckbox:    document.getElementById('pg-show-all-languages-checkbox'),
        kokoroSinglePanel:  document.getElementById('pg-kokoro-single-panel'),
        kokoroBlendPanel:   document.getElementById('pg-kokoro-blend-panel'),
        // PocketTTS sub-elements
        pocketModeSelector: document.getElementById('pg-pocket-mode-selector'),
        pocketPresetPanel:  document.getElementById('pg-pocket-preset-panel'),
        pocketClonePanel:   document.getElementById('pg-pocket-clone-panel'),
        pocketVoiceSelect:  document.getElementById('pg-pocket-voice-select'),
        pocketRefAudioInput:document.getElementById('pg-pocket-ref-audio'),
        pocketRefAudioName: document.getElementById('pg-pocket-ref-audio-name'),
        pocketRefAudioZone: document.getElementById('pg-pocket-ref-audio-zone'),
        // F5-TTS sub-elements
        f5RefAudioInput:    document.getElementById('pg-f5-ref-audio'),
        f5RefAudioName:     document.getElementById('pg-f5-ref-audio-name'),
        f5RefAudioZone:     document.getElementById('pg-f5-ref-audio-zone'),
        f5RefTextInput:     document.getElementById('pg-f5-ref-text'),
        // Common
        textArea:           document.getElementById('pg-text-input'),
        speedInput:         document.getElementById('pg-speed-input'),
        deviceSelect:       document.getElementById('pg-device-select'),
        synthesizeBtn:      document.getElementById('pg-synthesize-btn'),
        // Player
        playerSection:      document.getElementById('pg-player-section'),
        audioEl:            document.getElementById('pg-audio'),
        latencyBadge:       document.getElementById('pg-latency-badge'),
        playPauseBtn:       document.getElementById('pg-play-pause-btn'),
        progressBar:        document.getElementById('pg-progress-bar'),
        progressFill:       document.getElementById('pg-progress-fill'),
        currentTimeEl:      document.getElementById('pg-current-time'),
        durationEl:         document.getElementById('pg-duration'),
    };
}

// ── Synthesizer panel switching ────────────────────────────────────────────

function getActiveSynth(els) {
    const activeBtn = els.synthSelector
        ? els.synthSelector.querySelector('.pg-synth-pill.active')
        : null;
    return activeBtn ? activeBtn.getAttribute('data-synth') : 'kokoro';
}

function switchSynth(synth, els) {
    if (els.synthSelector) {
        els.synthSelector.querySelectorAll('.pg-synth-pill').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-synth') === synth);
        });
    }
    const panels = {
        kokoro:      els.kokoroPanel,
        'pocket-tts': els.pocketPanel,
        'f5-tts':    els.f5Panel,
    };
    Object.entries(panels).forEach(([key, panel]) => {
        if (panel) panel.style.display = key === synth ? 'block' : 'none';
    });
}

// ── Audio player helpers ───────────────────────────────────────────────────

function formatTime(secs) {
    if (!isFinite(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

function setupAudioPlayer(els, url) {
    const { audioEl, playerSection, playPauseBtn, progressBar, progressFill,
            currentTimeEl, durationEl } = els;

    if (!audioEl || !playerSection) return;

    // Revoke old object URL if any
    if (audioEl.src && audioEl.src.startsWith('blob:')) {
        URL.revokeObjectURL(audioEl.src);
    }

    audioEl.src = url;
    playerSection.style.display = 'block';

    audioEl.onloadedmetadata = () => {
        if (durationEl) durationEl.textContent = formatTime(audioEl.duration);
    };

    audioEl.ontimeupdate = () => {
        const pct = audioEl.duration ? (audioEl.currentTime / audioEl.duration) * 100 : 0;
        if (progressFill) progressFill.style.width = `${pct}%`;
        if (currentTimeEl) currentTimeEl.textContent = formatTime(audioEl.currentTime);
    };

    audioEl.onended = () => {
        if (playPauseBtn) playPauseBtn.textContent = '▶';
    };

    if (playPauseBtn) {
        playPauseBtn.onclick = () => {
            if (audioEl.paused) {
                audioEl.play();
                playPauseBtn.textContent = '⏸';
            } else {
                audioEl.pause();
                playPauseBtn.textContent = '▶';
            }
        };
        playPauseBtn.textContent = '⏸';
    }

    // Click on progress bar to seek
    if (progressBar) {
        progressBar.onclick = (e) => {
            const rect = progressBar.getBoundingClientRect();
            const ratio = (e.clientX - rect.left) / rect.width;
            audioEl.currentTime = ratio * audioEl.duration;
        };
    }

    audioEl.play().catch(() => {});
}

// ── Synthesis ──────────────────────────────────────────────────────────────

async function handleSynthesize(els) {
    const synth = getActiveSynth(els);
    const text = els.textArea ? els.textArea.value.trim() : '';
    const speed = els.speedInput ? parseFloat(els.speedInput.value) || 1.0 : 1.0;
    const device = els.deviceSelect ? els.deviceSelect.value : 'cpu';

    if (!text) {
        showToast('Please enter some text to synthesize.', 'error');
        return;
    }

    const body = new FormData();
    body.append('synthesizer', synth);
    body.append('text', text);
    body.append('speed', speed);
    body.append('device', device || 'cpu');

    // Collect synthesizer-specific params
    if (synth === 'kokoro') {
        const vfInput = els.voiceFormulaInput;
        const formula = vfInput ? vfInput.value.trim() : '';
        // Determine active mode from DOM pill
        const activeModePill = els.voiceModeSelector
            ? els.voiceModeSelector.querySelector('.mode-pill.active')
            : null;
        const mode = activeModePill ? activeModePill.getAttribute('data-mode') : 'single';
        const langCode = els.langSelect ? els.langSelect.value : 'a';

        body.append('lang_code', langCode);
        if (mode === 'blend' && formula) {
            body.append('voice_formula', formula);
        } else {
            const voice = els.voiceSelect ? els.voiceSelect.value : '';
            if (!voice) { showToast('Please select a Kokoro voice.', 'error'); return; }
            body.append('voice', voice);
        }

    } else if (synth === 'pocket-tts') {
        const params = getPocketVoiceParams({
            modeSelector:  els.pocketModeSelector,
            voiceSelect:   els.pocketVoiceSelect,
            refAudioInput: els.pocketRefAudioInput,
        });
        if (params.mode === 'clone' && !params.ref_audio_file) {
            showToast('Please upload a reference audio clip for clone mode.', 'error');
            return;
        }
        if (params.pocket_voice) body.append('pocket_voice', params.pocket_voice);
        if (params.ref_audio_file) body.append('ref_audio', params.ref_audio_file);

    } else if (synth === 'f5-tts') {
        const f5File = els.f5RefAudioInput && els.f5RefAudioInput.files[0];
        const f5Text = els.f5RefTextInput ? els.f5RefTextInput.value.trim() : '';
        if (!f5File) { showToast('Please upload a reference audio clip for F5-TTS.', 'error'); return; }
        if (!f5Text) { showToast('Please enter the reference text transcript for F5-TTS.', 'error'); return; }
        body.append('ref_audio', f5File);
        body.append('ref_text', f5Text);
    }

    // --- Synthesize ---
    const btn = els.synthesizeBtn;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="display:inline-block; width:0.85rem; height:0.85rem; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation:spin 0.8s linear infinite; margin-right:0.4rem; vertical-align:middle;"></span> Synthesizing…';
    }

    pgSynthStart = performance.now();

    try {
        const blob = await previewVoice(body);
        const elapsed = ((performance.now() - pgSynthStart) / 1000).toFixed(1);

        const url = URL.createObjectURL(blob);
        setupAudioPlayer(els, url);

        if (els.latencyBadge) {
            els.latencyBadge.textContent = `Synthesized in ${elapsed}s`;
            els.latencyBadge.style.display = 'inline-flex';
        }

        showToast(`Audio ready (${elapsed}s)`, 'success');
    } catch (err) {
        showToast(err.message || 'Synthesis failed.', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '▶ Synthesize & Play';
        }
    }
}

// ── File upload zone helper ────────────────────────────────────────────────

function setupUploadZone(zone, input, nameDisplay) {
    if (!zone || !input) return;

    ['dragover', 'dragenter'].forEach(evt => {
        zone.addEventListener(evt, e => { e.preventDefault(); zone.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(evt => {
        zone.addEventListener(evt, () => zone.classList.remove('dragover'));
    });
    zone.addEventListener('drop', e => {
        e.preventDefault();
        if (e.dataTransfer.files.length) {
            input.files = e.dataTransfer.files;
            if (nameDisplay) { nameDisplay.textContent = `📎 ${e.dataTransfer.files[0].name}`; nameDisplay.style.display = 'block'; }
        }
    });
    input.addEventListener('change', () => {
        if (input.files.length && nameDisplay) {
            nameDisplay.textContent = `📎 ${input.files[0].name}`;
            nameDisplay.style.display = 'block';
        }
    });
}

// ── Public init ────────────────────────────────────────────────────────────

export function initPlayground() {
    const els = getElements();

    // Synthesizer pill switcher
    if (els.synthSelector) {
        els.synthSelector.querySelectorAll('.pg-synth-pill').forEach(btn => {
            btn.addEventListener('click', () => switchSynth(btn.getAttribute('data-synth'), els));
        });
    }

    // Default: show Kokoro panel
    switchSynth('kokoro', els);

    // Set up Kokoro mixer using playground-specific element references
    setupKokoroMixer(els);
    updateFilteredVoices(els);
    renderPresets(els);

    // Set up PocketTTS mode toggle
    setupPocketModeToggle({
        modeSelector: els.pocketModeSelector,
        presetPanel:  els.pocketPresetPanel,
        clonePanel:   els.pocketClonePanel,
        voiceSelect:  els.pocketVoiceSelect,
    });

    // File upload zones
    setupUploadZone(els.pocketRefAudioZone, els.pocketRefAudioInput, els.pocketRefAudioName);
    setupUploadZone(els.f5RefAudioZone, els.f5RefAudioInput, els.f5RefAudioName);

    // Synthesize button
    if (els.synthesizeBtn) {
        els.synthesizeBtn.addEventListener('click', () => handleSynthesize(els));
    }
}
