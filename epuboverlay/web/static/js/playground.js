/**
 * playground.js — Voice Playground page controller.
 *
 * Manages synthesizer switching, voice configuration, synthesis requests,
 * and audio playback in the Voice Playground tab.
 */

import {
    previewVoice,
    fetchPlaygroundHistory,
    clearPlaygroundCache,
    saveReference
} from './api.js';
import { showToast } from './utils.js';
import { loadSavedReferencesGlobal, savedReferences } from './app.js';
import {
    setupKokoroMixer,
    updateFilteredVoices,
    renderPresets,
} from './kokoro.js';
import {
    setupPocketModeToggle,
    getPocketVoiceParams,
} from './pocket.js';

let pgAbortController = null;

let pgF5RecordedBlob = null;
let pgPocketRecordedBlob = null;

let pgF5Recorder = null;
let pgPocketRecorder = null;

let pgF5RecordTimer = null;
let pgPocketRecordTimer = null;

let pgF5RecordSeconds = 0;
let pgPocketRecordSeconds = 0;

let pgF5Chunks = [];
let pgPocketChunks = [];

// ── Playground DOM element references ──────────────────────────────────────

function getElements() {
    return {
        // Synthesizer selector
        synthSelector:      document.getElementById('pg-synth-selector'),
        // Panels
        kokoroPanel:        document.getElementById('pg-kokoro-panel'),
        pocketPanel:        document.getElementById('pg-pocket-panel'),
        f5Panel:            document.getElementById('pg-f5-panel'),
        // Kokoro sub-elements
        voiceModeSelector:  document.getElementById('pg-voice-mode-selector'),
        kokoroSinglePanel:  document.getElementById('pg-kokoro-single-panel'),
        kokoroBlendPanel:   document.getElementById('pg-kokoro-blend-panel'),
        langSelect:         document.getElementById('pg-lang-code-select'),
        voiceSelect:        document.getElementById('pg-voice-select'),
        blendVisualizerBar: document.getElementById('pg-blend-visualizer-bar'),
        blendChannelsList:  document.getElementById('pg-blend-channels-list'),
        voiceFormulaInput:  document.getElementById('pg-voice-formula-input'),
        blendAddSelect:     document.getElementById('pg-blend-add-select'),
        addToBlendBtn:      document.getElementById('pg-add-to-blend-btn'),
        formulaResetBtn:    document.getElementById('pg-formula-reset-btn'),
        saveBlendBtn:       document.getElementById('pg-save-blend-btn'),
        blendPresetsGrid:   document.getElementById('pg-blend-presets-grid'),
        showAllCheckbox:    document.getElementById('pg-show-all-languages-checkbox'),
        // PocketTTS sub-elements
        pocketModeSelector: document.getElementById('pg-pocket-mode-selector'),
        pocketPresetPanel:  document.getElementById('pg-pocket-preset-panel'),
        pocketClonePanel:   document.getElementById('pg-pocket-clone-panel'),
        pocketVoiceSelect:  document.getElementById('pg-pocket-voice-select'),
        pocketRefAudioInput:document.getElementById('pg-pocket-ref-audio'),
        pocketRefAudioName: document.getElementById('pg-pocket-ref-audio-name'),
        pocketRefAudioZone: document.getElementById('pg-pocket-ref-audio-zone'),
        pocketRefVoiceSelect: document.getElementById('pg-pocket-ref-voice-select'),
        // F5-TTS sub-elements
        f5RefAudioInput:    document.getElementById('pg-f5-ref-audio'),
        f5RefAudioName:     document.getElementById('pg-f5-ref-audio-name'),
        f5RefAudioZone:     document.getElementById('pg-f5-ref-audio-zone'),
        f5RefTextInput:     document.getElementById('pg-f5-ref-text'),
        f5RefVoiceSelect:   document.getElementById('pg-f5-ref-voice-select'),
        // Common
        textArea:           document.getElementById('pg-text-input'),
        speedInput:         document.getElementById('pg-speed-input'),
        deviceSelect:       document.getElementById('pg-device-select'),
        synthesizeBtn:      document.getElementById('pg-synthesize-btn'),
        cancelBtn:          document.getElementById('pg-cancel-btn'),
        // History List
        historySection:     document.getElementById('pg-history-section'),
        historyList:        document.getElementById('pg-history-list'),
        clearHistoryBtn:    document.getElementById('pg-clear-history-btn'),
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
    if (!isFinite(secs) || isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

// ── Rendering Stacked History ──────────────────────────────────────────────

export async function refreshPlaygroundList() {
    const els = getElements();
    if (!els.historyList) return;

    try {
        const history = await fetchPlaygroundHistory();
        els.historyList.innerHTML = '';
        if (history.length === 0) {
            els.historySection.style.display = 'none';
            return;
        }

        els.historySection.style.display = 'block';

        history.forEach(item => {
            const card = document.createElement('div');
            card.className = 'pg-history-card';
            
            // Build Settings badges
            let settingsHtml = '';
            if (item.synthesizer === 'kokoro') {
                const langMap = { 'a': 'US', 'b': 'GB', 'e': 'ES', 'f': 'FR', 'h': 'IN', 'i': 'IT', 'j': 'JP', 'p': 'PT', 'z': 'ZH' };
                const langLabel = langMap[item.settings.lang_code] || item.settings.lang_code;
                settingsHtml += `<span class="pg-meta-badge settings">${langLabel}</span>`;
                if (item.settings.voice_formula) {
                    settingsHtml += `<span class="pg-meta-badge settings" title="${escapeHtml(item.settings.voice_formula)}">formula: mix</span>`;
                } else {
                    settingsHtml += `<span class="pg-meta-badge settings">${item.settings.voice}</span>`;
                }
            } else if (item.synthesizer === 'pocket-tts') {
                if (item.settings.pocket_voice) {
                    settingsHtml += `<span class="pg-meta-badge settings">${item.settings.pocket_voice} (preset)</span>`;
                } else {
                    settingsHtml += `<span class="pg-meta-badge settings">cloning</span>`;
                }
            } else if (item.synthesizer === 'f5-tts') {
                settingsHtml += `<span class="pg-meta-badge settings">cloning</span>`;
            }
            settingsHtml += `<span class="pg-meta-badge settings">${item.settings.speed}x</span>`;
            settingsHtml += `<span class="pg-meta-badge settings">${item.settings.device}</span>`;

            card.innerHTML = `
                <div class="pg-history-meta">
                    <span class="pg-meta-badge ${item.synthesizer}">${item.synthesizer}</span>
                    ${settingsHtml}
                    <span style="font-size:0.75rem; color:var(--text-muted); margin-left:auto;">${new Date(item.timestamp * 1000).toLocaleTimeString()}</span>
                </div>
                <div class="pg-history-text">${escapeHtml(item.text)}</div>
                <div class="pg-history-player">
                    <button type="button" class="pg-history-play-btn">▶</button>
                    <div class="pg-history-progress-container">
                        <div class="pg-history-progress-fill"></div>
                    </div>
                    <span class="pg-history-time">0:00 / 0:00</span>
                    <a href="/api/playground/audio/${item.id}" download="playground_${item.id}.wav" class="pg-history-dl-btn" title="Download Audio">📥</a>
                    <audio src="/api/playground/audio/${item.id}" preload="none"></audio>
                </div>
            `;

            // Setup Custom Playback
            const audio = card.querySelector('audio');
            const playBtn = card.querySelector('.pg-history-play-btn');
            const progressContainer = card.querySelector('.pg-history-progress-container');
            const progressFill = card.querySelector('.pg-history-progress-fill');
            const timeEl = card.querySelector('.pg-history-time');

            audio.onloadedmetadata = () => {
                timeEl.textContent = `0:00 / ${formatTime(audio.duration)}`;
            };
            audio.ontimeupdate = () => {
                const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
                progressFill.style.width = `${pct}%`;
                timeEl.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
            };
            audio.onended = () => {
                playBtn.textContent = '▶';
            };
            playBtn.onclick = () => {
                if (audio.paused) {
                    // Pause other audios
                    document.querySelectorAll('.pg-history-list audio').forEach(a => {
                        if (a !== audio) {
                            a.pause();
                            const otherCard = a.closest('.pg-history-card');
                            if (otherCard) otherCard.querySelector('.pg-history-play-btn').textContent = '▶';
                        }
                    });
                    audio.play().catch(e => showToast('Playback failed: ' + e.message, 'error'));
                    playBtn.textContent = '⏸';
                } else {
                    audio.pause();
                    playBtn.textContent = '▶';
                }
            };
            progressContainer.onclick = (e) => {
                const rect = progressContainer.getBoundingClientRect();
                const ratio = (e.clientX - rect.left) / rect.width;
                audio.currentTime = ratio * audio.duration;
            };

            els.historyList.appendChild(card);
        });

    } catch (err) {
        showToast('Failed to load playground history: ' + err.message, 'error');
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#039;');
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
        
        if (params.mode === 'clone') {
            const savedVoiceId = els.pocketRefVoiceSelect ? els.pocketRefVoiceSelect.value : '';
            if (savedVoiceId) {
                body.append('ref_id', savedVoiceId);
            } else {
                if (pgPocketRecordedBlob) {
                    body.append('ref_audio', pgPocketRecordedBlob, 'recorded_prompt.wav');
                } else if (params.ref_audio_file) {
                    body.append('ref_audio', params.ref_audio_file);
                } else {
                    showToast('Please select a saved voice, upload a clip, or record audio for clone mode.', 'error');
                    return;
                }
            }
        } else {
            if (params.pocket_voice) body.append('pocket_voice', params.pocket_voice);
        }

    } else if (synth === 'f5-tts') {
        const savedVoiceId = els.f5RefVoiceSelect ? els.f5RefVoiceSelect.value : '';
        const f5Text = els.f5RefTextInput ? els.f5RefTextInput.value.trim() : '';
        
        if (savedVoiceId) {
            body.append('ref_id', savedVoiceId);
            // Reference text is optional since it's saved, but we can override it if they write something else
            if (f5Text) body.append('ref_text', f5Text);
        } else {
            const f5File = els.f5RefAudioInput && els.f5RefAudioInput.files[0];
            if (pgF5RecordedBlob) {
                body.append('ref_audio', pgF5RecordedBlob, 'recorded_prompt.wav');
            } else if (f5File) {
                body.append('ref_audio', f5File);
            } else {
                showToast('Please select a saved voice, upload a clip, or record audio for F5-TTS.', 'error');
                return;
            }
            if (!f5Text) {
                showToast('Please enter the reference text transcript for F5-TTS.', 'error');
                return;
            }
            body.append('ref_text', f5Text);
        }
    }

    // --- Synthesize ---
    const btn = els.synthesizeBtn;
    const cancelBtn = els.cancelBtn;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner" style="display:inline-block; width:0.85rem; height:0.85rem; border:2px solid rgba(255,255,255,0.3); border-top-color:#fff; border-radius:50%; animation:spin 0.8s linear infinite; margin-right:0.4rem; vertical-align:middle;"></span> Synthesizing…';
    }
    if (cancelBtn) {
        cancelBtn.disabled = false;
    }

    const pgSynthStart = performance.now();
    pgAbortController = new AbortController();

    try {
        await previewVoice(body, pgAbortController.signal);
        const elapsed = ((performance.now() - pgSynthStart) / 1000).toFixed(1);

        showToast(`Audio synthesized successfully in ${elapsed}s!`, 'success');
        await refreshPlaygroundList();
    } catch (err) {
        if (err.name === 'AbortError') {
            showToast('Synthesis cancelled.', 'info');
        } else {
            showToast(err.message || 'Synthesis failed.', 'error');
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '▶ Synthesize';
        }
        if (cancelBtn) {
            cancelBtn.disabled = true;
        }
        pgAbortController = null;
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

// ── Recorder Setup Helpers ──────────────────────────────────────────────────

function initPlaygroundRecorders() {
    // F5 Source toggling
    const f5UploadSwitchBtn = document.getElementById('pg-f5-source-upload');
    const f5RecordSwitchBtn = document.getElementById('pg-f5-source-record');
    const f5UploadGroup = document.getElementById('pg-f5-upload-container');
    const f5RecordGroup = document.getElementById('pg-f5-recorder-container');

    if (f5UploadSwitchBtn && f5RecordSwitchBtn && f5UploadGroup && f5RecordGroup) {
        f5UploadSwitchBtn.addEventListener('click', () => {
            f5UploadSwitchBtn.classList.add('active-source', 'btn-primary');
            f5UploadSwitchBtn.classList.remove('btn-ghost');
            f5RecordSwitchBtn.classList.remove('active-source', 'btn-primary');
            f5RecordSwitchBtn.classList.add('btn-ghost');
            f5UploadGroup.style.display = 'block';
            f5RecordGroup.style.display = 'none';
        });

        f5RecordSwitchBtn.addEventListener('click', () => {
            f5RecordSwitchBtn.classList.add('active-source', 'btn-primary');
            f5RecordSwitchBtn.classList.remove('btn-ghost');
            f5UploadSwitchBtn.classList.remove('active-source', 'btn-primary');
            f5UploadSwitchBtn.classList.add('btn-ghost');
            f5UploadGroup.style.display = 'none';
            f5RecordGroup.style.display = 'block';
        });
    }

    // F5 Recorder Events
    const f5StartBtn = document.querySelector('#pg-f5-recorder-container .rec-btn-start');
    const f5StopBtn = document.querySelector('#pg-f5-recorder-container .rec-btn-stop');
    const f5StatusEl = document.querySelector('#pg-f5-recorder-container .rec-status');
    const f5TimerEl = document.querySelector('#pg-f5-recorder-container .rec-timer');
    const f5PreviewEl = document.querySelector('#pg-f5-recorder-container .rec-audio-preview');
    const f5SaveBox = document.querySelector('#pg-f5-recorder-container .rec-preview-group');
    const f5SaveBtn = document.querySelector('#pg-f5-recorder-container .rec-btn-save');
    const f5SaveName = document.querySelector('#pg-f5-recorder-container .rec-voice-name');

    if (f5StartBtn && f5StopBtn && f5StatusEl && f5TimerEl && f5PreviewEl) {
        f5StartBtn.addEventListener('click', async () => {
            pgF5Chunks = [];
            pgF5RecordSeconds = 0;
            f5TimerEl.textContent = '00:00';
            f5StatusEl.textContent = 'Recording...';
            f5StatusEl.previousElementSibling.classList.add('pulsing');
            f5PreviewEl.style.display = 'none';
            f5SaveBox.style.display = 'none';
            pgF5RecordedBlob = null;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                pgF5Recorder = new MediaRecorder(stream);
                pgF5Recorder.ondataavailable = e => {
                    if (e.data.size > 0) pgF5Chunks.push(e.data);
                };
                pgF5Recorder.onstop = () => {
                    pgF5RecordedBlob = new Blob(pgF5Chunks, { type: 'audio/wav' });
                    f5PreviewEl.src = URL.createObjectURL(pgF5RecordedBlob);
                    f5PreviewEl.style.display = 'block';
                    f5SaveBox.style.display = 'flex';
                    f5StatusEl.textContent = 'Recording completed';
                    f5StatusEl.previousElementSibling.classList.remove('pulsing');
                    stream.getTracks().forEach(track => track.stop());
                };
                pgF5Recorder.start();
                f5StartBtn.disabled = true;
                f5StopBtn.disabled = false;

                pgF5RecordTimer = setInterval(() => {
                    pgF5RecordSeconds++;
                    const m = Math.floor(pgF5RecordSeconds / 60).toString().padStart(2, '0');
                    const s = (pgF5RecordSeconds % 60).toString().padStart(2, '0');
                    f5TimerEl.textContent = `${m}:${s}`;
                }, 1000);
            } catch (err) {
                showToast('Could not access microphone: ' + err.message, 'error');
                f5StatusEl.textContent = 'Microphone error';
                f5StatusEl.previousElementSibling.classList.remove('pulsing');
            }
        });

        f5StopBtn.addEventListener('click', () => {
            if (pgF5Recorder && pgF5Recorder.state !== 'inactive') {
                pgF5Recorder.stop();
                clearInterval(pgF5RecordTimer);
                f5StartBtn.disabled = false;
                f5StopBtn.disabled = true;
            }
        });

        f5SaveBtn.addEventListener('click', async () => {
            const name = f5SaveName.value.trim();
            const transcript = document.getElementById('pg-f5-ref-text').value.trim();

            if (!name) {
                showToast('Please enter a voice name.', 'error');
                return;
            }
            if (!pgF5RecordedBlob) {
                showToast('No voice recorded yet.', 'error');
                return;
            }

            const body = new FormData();
            body.append('name', name);
            body.append('text', transcript);
            body.append('audio', pgF5RecordedBlob, `${name.replace(/\s+/g, '_')}_playground_f5.wav`);

            try {
                f5SaveBtn.disabled = true;
                const saved = await saveReference(body);
                showToast(`Voice "${name}" saved to library successfully!`, 'success');
                
                // Refresh references lists & select newly saved voice
                await loadSavedReferencesGlobal();
                document.getElementById('pg-f5-ref-voice-select').value = saved.id;
                document.getElementById('pg-f5-ref-voice-select').dispatchEvent(new Event('change'));

                // Reset recorder UI
                f5SaveName.value = '';
                f5SaveBox.style.display = 'none';
                f5PreviewEl.src = '';
                f5PreviewEl.style.display = 'none';
                f5TimerEl.textContent = '00:00';
                f5StatusEl.textContent = 'Ready to record';
                pgF5RecordedBlob = null;
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                f5SaveBtn.disabled = false;
            }
        });
    }

    // Pocket Source Toggling
    const pocketUploadSwitchBtn = document.getElementById('pg-pocket-source-upload');
    const pocketRecordSwitchBtn = document.getElementById('pg-pocket-source-record');
    const pocketUploadGroup = document.getElementById('pg-pocket-upload-container');
    const pocketRecordGroup = document.getElementById('pg-pocket-recorder-container');

    if (pocketUploadSwitchBtn && pocketRecordSwitchBtn && pocketUploadGroup && pocketRecordGroup) {
        pocketUploadSwitchBtn.addEventListener('click', () => {
            pocketUploadSwitchBtn.classList.add('active-source', 'btn-primary');
            pocketUploadSwitchBtn.classList.remove('btn-ghost');
            pocketRecordSwitchBtn.classList.remove('active-source', 'btn-primary');
            pocketRecordSwitchBtn.classList.add('btn-ghost');
            pocketUploadGroup.style.display = 'block';
            pocketRecordGroup.style.display = 'none';
        });

        pocketRecordSwitchBtn.addEventListener('click', () => {
            pocketRecordSwitchBtn.classList.add('active-source', 'btn-primary');
            pocketRecordSwitchBtn.classList.remove('btn-ghost');
            pocketUploadSwitchBtn.classList.remove('active-source', 'btn-primary');
            pocketUploadSwitchBtn.classList.add('btn-ghost');
            pocketUploadGroup.style.display = 'none';
            pocketRecordGroup.style.display = 'block';
        });
    }

    // Pocket Recorder Events
    const pocketStartBtn = document.querySelector('#pg-pocket-recorder-container .rec-btn-start');
    const pocketStopBtn = document.querySelector('#pg-pocket-recorder-container .rec-btn-stop');
    const pocketStatusEl = document.querySelector('#pg-pocket-recorder-container .rec-status');
    const pocketTimerEl = document.querySelector('#pg-pocket-recorder-container .rec-timer');
    const pocketPreviewEl = document.querySelector('#pg-pocket-recorder-container .rec-audio-preview');
    const pocketSaveBox = document.querySelector('#pg-pocket-recorder-container .rec-preview-group');
    const pocketSaveBtn = document.querySelector('#pg-pocket-recorder-container .rec-btn-save');
    const pocketSaveName = document.querySelector('#pg-pocket-recorder-container .rec-voice-name');

    if (pocketStartBtn && pocketStopBtn && pocketStatusEl && pocketTimerEl && pocketPreviewEl) {
        pocketStartBtn.addEventListener('click', async () => {
            pgPocketChunks = [];
            pgPocketRecordSeconds = 0;
            pocketTimerEl.textContent = '00:00';
            pocketStatusEl.textContent = 'Recording...';
            pocketStatusEl.previousElementSibling.classList.add('pulsing');
            pocketPreviewEl.style.display = 'none';
            pocketSaveBox.style.display = 'none';
            pgPocketRecordedBlob = null;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                pgPocketRecorder = new MediaRecorder(stream);
                pgPocketRecorder.ondataavailable = e => {
                    if (e.data.size > 0) pgPocketChunks.push(e.data);
                };
                pgPocketRecorder.onstop = () => {
                    pgPocketRecordedBlob = new Blob(pgPocketChunks, { type: 'audio/wav' });
                    pocketPreviewEl.src = URL.createObjectURL(pgPocketRecordedBlob);
                    pocketPreviewEl.style.display = 'block';
                    pocketSaveBox.style.display = 'flex';
                    pocketStatusEl.textContent = 'Recording completed';
                    pocketStatusEl.previousElementSibling.classList.remove('pulsing');
                    stream.getTracks().forEach(track => track.stop());
                };
                pgPocketRecorder.start();
                pocketStartBtn.disabled = true;
                pocketStopBtn.disabled = false;

                pgPocketRecordTimer = setInterval(() => {
                    pgPocketRecordSeconds++;
                    const m = Math.floor(pgPocketRecordSeconds / 60).toString().padStart(2, '0');
                    const s = (pgPocketRecordSeconds % 60).toString().padStart(2, '0');
                    pocketTimerEl.textContent = `${m}:${s}`;
                }, 1000);
            } catch (err) {
                showToast('Could not access microphone: ' + err.message, 'error');
                pocketStatusEl.textContent = 'Microphone error';
                pocketStatusEl.previousElementSibling.classList.remove('pulsing');
            }
        });

        pocketStopBtn.addEventListener('click', () => {
            if (pgPocketRecorder && pgPocketRecorder.state !== 'inactive') {
                pgPocketRecorder.stop();
                clearInterval(pgPocketRecordTimer);
                pocketStartBtn.disabled = false;
                pocketStopBtn.disabled = true;
            }
        });

        pocketSaveBtn.addEventListener('click', async () => {
            const name = pocketSaveName.value.trim();

            if (!name) {
                showToast('Please enter a voice name.', 'error');
                return;
            }
            if (!pgPocketRecordedBlob) {
                showToast('No voice recorded yet.', 'error');
                return;
            }

            const body = new FormData();
            body.append('name', name);
            body.append('text', '');
            body.append('audio', pgPocketRecordedBlob, `${name.replace(/\s+/g, '_')}_playground_pocket.wav`);

            try {
                pocketSaveBtn.disabled = true;
                const saved = await saveReference(body);
                showToast(`Voice "${name}" saved to library successfully!`, 'success');
                
                // Refresh references lists & select newly saved voice
                await loadSavedReferencesGlobal();
                document.getElementById('pg-pocket-ref-voice-select').value = saved.id;
                document.getElementById('pg-pocket-ref-voice-select').dispatchEvent(new Event('change'));

                // Reset recorder UI
                pocketSaveName.value = '';
                pocketSaveBox.style.display = 'none';
                pocketPreviewEl.src = '';
                pocketPreviewEl.style.display = 'none';
                pocketTimerEl.textContent = '00:00';
                pocketStatusEl.textContent = 'Ready to record';
                pgPocketRecordedBlob = null;
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                pocketSaveBtn.disabled = false;
            }
        });
    }

    // Playground Dropdowns Toggling
    const pgF5Select = document.getElementById('pg-f5-ref-voice-select');
    const pgF5CustomGroup = document.getElementById('pg-f5-custom-group');
    const pgF5RefTextInput = document.getElementById('pg-f5-ref-text');

    if (pgF5Select && pgF5CustomGroup) {
        pgF5Select.addEventListener('change', () => {
            const val = pgF5Select.value;
            if (val) {
                pgF5CustomGroup.style.display = 'none';
                // Find saved transcript
                const ref = savedReferences.find(r => r.id === val);
                if (ref) {
                    pgF5RefTextInput.value = ref.text || '';
                    pgF5RefTextInput.readOnly = true;
                    pgF5RefTextInput.style.background = 'var(--bg-secondary)';
                }
            } else {
                pgF5CustomGroup.style.display = 'block';
                pgF5RefTextInput.value = '';
                pgF5RefTextInput.readOnly = false;
                pgF5RefTextInput.style.background = '';
            }
        });
    }

    const pgPocketSelect = document.getElementById('pg-pocket-ref-voice-select');
    const pgPocketCustomGroup = document.getElementById('pg-pocket-custom-group');

    if (pgPocketSelect && pgPocketCustomGroup) {
        pgPocketSelect.addEventListener('change', () => {
            if (pgPocketSelect.value) {
                pgPocketCustomGroup.style.display = 'none';
            } else {
                pgPocketCustomGroup.style.display = 'block';
            }
        });
    }
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

    // Initialize mic recording source toggles and events
    initPlaygroundRecorders();

    // Synthesize button
    if (els.synthesizeBtn) {
        els.synthesizeBtn.addEventListener('click', () => handleSynthesize(els));
    }

    // Cancel button
    if (els.cancelBtn) {
        els.cancelBtn.addEventListener('click', () => {
            if (pgAbortController) {
                pgAbortController.abort();
            }
        });
    }

    // Clear Cache Button
    if (els.clearHistoryBtn) {
        els.clearHistoryBtn.addEventListener('click', async () => {
            try {
                els.clearHistoryBtn.disabled = true;
                await clearPlaygroundCache();
                showToast('Playground cache cleared from server RAM.', 'success');
                await refreshPlaygroundList();
            } catch (err) {
                showToast('Failed to clear cache: ' + err.message, 'error');
            } finally {
                els.clearHistoryBtn.disabled = false;
            }
        });
    }

    // Load initial playground history stack
    refreshPlaygroundList();
}
