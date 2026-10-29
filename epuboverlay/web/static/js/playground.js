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
    saveReference,
} from './api.js?v=8';
import {
    showToast,
    escapeHtml,
    formatPlayerTime,
    getInstalledSynthesizers,
    getPreferredInstalledSynthesizer,
    setupAudioRecorder,
    SCENARIO_PROFILES,
} from './utils.js?v=8';
import { loadSavedReferencesGlobal, savedReferences } from './references.js?v=8';
import {
    setupKokoroMixer,
    updateFilteredVoices,
    renderPresets,
} from './kokoro.js?v=8';
import {
    setupPocketModeToggle,
    getPocketVoiceParams,
} from './pocket.js?v=8';

let pgAbortController = null;

let pgF5RecordedBlob = null;
let pgPocketRecordedBlob = null;

const LANGUAGE_SAMPLES = {
    en: 'The quick brown fox jumps over the lazy dog. "Wait a moment," she whispered, "do you hear that voice echoing across the library?"',
    ru: 'В тишине старинной библиотеки звучал тёплый, выразительный голос, оживляющий страницы забытых романов.',
    ko: '고요한 도서관 안에서 따뜻한 목소리가 울려 퍼지며, 오래된 책 속의 이야기를 생생하게 들려주었습니다.',
    ja: '静かな図書館の中で、温かく表現力豊かな声が響き渡り、物語の世界へと誘いました。',
    zh: '在宁静的图书馆里，温暖而富有表现力的声音缓缓响起，将书页中的故事娓娓道来。',
    de: 'In der Stille der alten Bibliothek erklang eine warme, ausdrucksstarke Stimme, die die Geschichten zum Leben erweckte.',
    es: 'En el silencio de la antigua biblioteca, resonó una voz cálida y expresiva que dio vida a cada página del libro.',
};

// ── Playground DOM element references ──────────────────────────────────────

function getElements() {
    return {
        // Synthesizer selector
        synthSelector:      document.getElementById('pg-synth-selector'),
        // Panels
        kokoroPanel:        document.getElementById('pg-kokoro-panel'),
        pocketPanel:        document.getElementById('pg-pocket-panel'),
        qwenPanel:          document.getElementById('pg-qwen3-panel'),
        supertonicPanel:    document.getElementById('pg-supertonic-panel'),
        supertonicVoiceSelect:    document.getElementById('pg-supertonic-voice-select'),
        supertonicLanguageSelect: document.getElementById('pg-supertonic-language-select'),
        supertonicStepsInput:     document.getElementById('pg-supertonic-steps-input'),
        f5Panel:            document.getElementById('pg-f5-panel'),
        dummyPanel:         document.getElementById('pg-dummy-panel'),
        emotionDirectorPanel: document.getElementById('pg-emotion-director-panel'),
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
        pocketLanguageSelect: document.getElementById('pg-pocket-language-select'),
        pocketDialogueVoiceSelect: document.getElementById('pg-pocket-dialogue-voice-select'),
        pocketTempInput:    document.getElementById('pg-pocket-temp-input'),
        pocketLsdInput:     document.getElementById('pg-pocket-lsd-input'),
        pocketNoiseClampInput: document.getElementById('pg-pocket-noise-clamp-input'),
        pocketEosInput:     document.getElementById('pg-pocket-eos-input'),
        pocketFramesEosInput: document.getElementById('pg-pocket-frames-eos-input'),
        pocketQuantizeCheckbox: document.getElementById('pg-pocket-quantize-checkbox'),
        pocketRefAudioInput:document.getElementById('pg-pocket-ref-audio'),
        pocketRefAudioName: document.getElementById('pg-pocket-ref-audio-name'),
        pocketRefAudioZone: document.getElementById('pg-pocket-ref-audio-zone'),
        pocketRefVoiceSelect: document.getElementById('pg-pocket-ref-voice-select'),
        // Qwen3-TTS sub-elements
        qwenVoiceModeSelector: document.getElementById('pg-qwen-voice-mode-selector'),
        qwenModeSelect:     document.getElementById('pg-qwen-mode-select'),
        qwenModelSelect:    document.getElementById('pg-qwen-model-select'),
        qwenSpeakerSelect:  document.getElementById('pg-qwen-speaker-select'),
        qwenSpeakerGroup:   document.getElementById('pg-qwen-speaker-group'),
        qwenLanguageSelect: document.getElementById('pg-qwen-language-select'),
        qwenRefGroup:       document.getElementById('pg-qwen-ref-group'),
        qwenRefVoiceSelect: document.getElementById('pg-qwen-ref-voice-select'),
        // Shared Emotion Instruct
        instructInput:      document.getElementById('pg-instruct-input'),
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

function updatePlaygroundClonePanelVisibility(els) {
    const synth = getActiveSynth(els);
    const qwenMode = els.qwenModeSelect ? els.qwenModeSelect.value : 'custom_voice';

    if (els.qwenSpeakerGroup) {
        els.qwenSpeakerGroup.style.display = qwenMode === 'custom_voice' ? 'flex' : 'none';
    }
    if (els.qwenRefGroup) {
        els.qwenRefGroup.style.display = qwenMode === 'clone' ? 'block' : 'none';
    }

    const showSharedCloneStudio =
        synth === 'f5-tts' ||
        (synth === 'qwen3-tts' && qwenMode === 'clone');

    if (els.f5Panel) {
        els.f5Panel.style.display = showSharedCloneStudio ? 'block' : 'none';
    }
}

function switchSynth(synth, els) {
    if (els.synthSelector) {
        els.synthSelector.querySelectorAll('.pg-synth-pill').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-synth') === synth);
        });
    }
    const panels = {
        kokoro:        els.kokoroPanel,
        'pocket-tts':  els.pocketPanel,
        'qwen3-tts':   els.qwenPanel,
        supertonic:    els.supertonicPanel,
        dummy:         els.dummyPanel,
    };
    Object.entries(panels).forEach(([key, panel]) => {
        if (panel) panel.style.display = key === synth ? 'block' : 'none';
    });
    if (els.emotionDirectorPanel) {
        els.emotionDirectorPanel.style.display =
            (synth === 'qwen3-tts') ? 'block' : 'none';
    }
    updatePlaygroundClonePanelVisibility(els);
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
                settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(langLabel)}</span>`;
                if (item.settings.voice_formula) {
                    settingsHtml += `<span class="pg-meta-badge settings" title="${escapeHtml(item.settings.voice_formula)}">formula: mix</span>`;
                } else {
                    settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.voice)}</span>`;
                }
            } else if (item.synthesizer === 'pocket-tts') {
                if (item.settings.pocket_voice) {
                    settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.pocket_voice)}</span>`;
                } else {
                    settingsHtml += `<span class="pg-meta-badge settings">cloning</span>`;
                }
                if (item.settings.pocket_language && item.settings.pocket_language !== 'english') {
                    settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.pocket_language)}</span>`;
                }
                if (item.settings.temp) {
                    settingsHtml += `<span class="pg-meta-badge settings">T=${escapeHtml(item.settings.temp)}</span>`;
                }
            } else if (item.synthesizer === 'qwen3-tts') {
                settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.qwen_mode || 'custom_voice')}</span>`;
                if (item.settings.qwen_speaker) {
                    settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.qwen_speaker)}</span>`;
                }
                if (item.settings.language) {
                    settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.language)}</span>`;
                }
            } else if (item.synthesizer === 'f5-tts') {
                settingsHtml += `<span class="pg-meta-badge settings">cloning</span>`;
            }
            settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.speed)}x</span>`;
            settingsHtml += `<span class="pg-meta-badge settings">${escapeHtml(item.settings.device)}</span>`;

            const safeSynth = escapeHtml(item.synthesizer);
            const safeId = encodeURIComponent(item.id || '');
            card.innerHTML = `
                <div class="pg-history-meta">
                    <span class="pg-meta-badge ${safeSynth}">${safeSynth}</span>
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
                    <a href="/api/playground/audio/${safeId}" download="playground_${safeId}.wav" class="pg-history-dl-btn" title="Download Audio">📥</a>
                    <audio src="/api/playground/audio/${safeId}" preload="none"></audio>
                </div>
            `;

            // Setup Custom Playback
            const audio = card.querySelector('audio');
            const playBtn = card.querySelector('.pg-history-play-btn');
            const progressContainer = card.querySelector('.pg-history-progress-container');
            const progressFill = card.querySelector('.pg-history-progress-fill');
            const timeEl = card.querySelector('.pg-history-time');

            audio.onloadedmetadata = () => {
                timeEl.textContent = `0:00 / ${formatPlayerTime(audio.duration)}`;
            };
            audio.ontimeupdate = () => {
                const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
                progressFill.style.width = `${pct}%`;
                timeEl.textContent = `${formatPlayerTime(audio.currentTime)} / ${formatPlayerTime(audio.duration)}`;
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

// ── Synthesis ──────────────────────────────────────────────────────────────

let _isSynthesizing = false;

async function handleSynthesize(els) {
    if (_isSynthesizing) return;
    const synth = getActiveSynth(els);
    const text = els.textArea ? els.textArea.value.trim() : '';
    const speed = els.speedInput ? parseFloat(els.speedInput.value) || 1.0 : 1.0;
    const device = els.deviceSelect ? els.deviceSelect.value : '';

    if (!text) {
        showToast('Please enter some text to synthesize.', 'error');
        return;
    }

    _isSynthesizing = true;

    const body = new FormData();
    body.append('synthesizer', synth);
    body.append('text', text);
    body.append('speed', speed);
    body.append('device', device);

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
            modeSelector:        els.pocketModeSelector,
            voiceSelect:         els.pocketVoiceSelect,
            refAudioInput:       els.pocketRefAudioInput,
            languageSelect:      els.pocketLanguageSelect,
            dialogueVoiceSelect: els.pocketDialogueVoiceSelect,
            tempInput:           els.pocketTempInput,
            lsdInput:            els.pocketLsdInput,
            noiseClampInput:     els.pocketNoiseClampInput,
            eosInput:            els.pocketEosInput,
            framesEosInput:      els.pocketFramesEosInput,
            quantizeCheckbox:    els.pocketQuantizeCheckbox,
        });

        body.append('pocket_language', params.pocket_language || 'english');
        if (params.dialogue_voice) body.append('dialogue_voice', params.dialogue_voice);
        body.append('temp', params.temp ?? 0.7);
        body.append('lsd_decode_steps', params.lsd_decode_steps ?? 1);
        if (params.noise_clamp !== null && !isNaN(params.noise_clamp)) {
            body.append('noise_clamp', params.noise_clamp);
        }
        body.append('eos_threshold', params.eos_threshold ?? -4.0);
        if (params.frames_after_eos !== null && !isNaN(params.frames_after_eos)) {
            body.append('frames_after_eos', params.frames_after_eos);
        }
        body.append('quantize', params.quantize ? 'true' : 'false');
        
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

    } else if (synth === 'supertonic') {
        body.append('supertonic_voice', els.supertonicVoiceSelect ? els.supertonicVoiceSelect.value : 'F1');
        body.append('language', els.supertonicLanguageSelect ? els.supertonicLanguageSelect.value : 'auto');
        body.append('supertonic_steps', els.supertonicStepsInput ? els.supertonicStepsInput.value : 8);

    } else if (synth === 'qwen3-tts') {
        const qwenMode = els.qwenModeSelect ? els.qwenModeSelect.value : 'custom_voice';
        const qwenModel = els.qwenModelSelect ? els.qwenModelSelect.value : 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice';
        const qwenSpeaker = els.qwenSpeakerSelect ? els.qwenSpeakerSelect.value : 'Ryan';
        const qwenLang = els.qwenLanguageSelect ? els.qwenLanguageSelect.value : 'Auto';
        const instruct = els.instructInput ? els.instructInput.value.trim() : '';

        body.append('qwen_mode', qwenMode);
        body.append('qwen_model', qwenModel);
        body.append('qwen_speaker', qwenSpeaker);
        body.append('language', qwenLang);
        if (instruct) body.append('instruct', instruct);

        if (qwenMode === 'clone') {
            const savedId = (els.qwenRefVoiceSelect && els.qwenRefVoiceSelect.value)
                || (els.f5RefVoiceSelect && els.f5RefVoiceSelect.value) || '';
            const refText = els.f5RefTextInput ? els.f5RefTextInput.value.trim() : '';
            const customFile = els.f5RefAudioInput && els.f5RefAudioInput.files[0];
            if (savedId) {
                body.append('ref_id', savedId);
                if (refText) body.append('ref_text', refText);
            } else if (pgF5RecordedBlob) {
                body.append('ref_audio', pgF5RecordedBlob, 'recorded_prompt.wav');
                if (refText) body.append('ref_text', refText);
            } else if (customFile) {
                body.append('ref_audio', customFile);
                if (refText) body.append('ref_text', refText);
            } else {
                showToast('Please select a saved reference voice, upload a voice clip, or record audio for Qwen3-TTS cloning.', 'error');
                return;
            }
        } else if (qwenMode === 'voice_design' && !instruct) {
            showToast('Please enter an Emotion & Intonation prompt to design a voice.', 'error');
            return;
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
        _isSynthesizing = false;
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
    const f5RecorderCtrl = setupAudioRecorder('#pg-f5-recorder-container', blob => {
        pgF5RecordedBlob = blob;
    });
    const f5SaveBtn = document.querySelector('#pg-f5-recorder-container .rec-btn-save');
    const f5SaveName = document.querySelector('#pg-f5-recorder-container .rec-voice-name');

    if (f5SaveBtn && f5SaveName) {
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
                
                await loadSavedReferencesGlobal();
                document.getElementById('pg-f5-ref-voice-select').value = saved.id;
                document.getElementById('pg-f5-ref-voice-select').dispatchEvent(new Event('change'));

                f5SaveName.value = '';
                if (f5RecorderCtrl) f5RecorderCtrl.reset();
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
    const pocketRecorderCtrl = setupAudioRecorder('#pg-pocket-recorder-container', blob => {
        pgPocketRecordedBlob = blob;
    });
    const pocketSaveBtn = document.querySelector('#pg-pocket-recorder-container .rec-btn-save');
    const pocketSaveName = document.querySelector('#pg-pocket-recorder-container .rec-voice-name');

    if (pocketSaveBtn && pocketSaveName) {
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
                
                await loadSavedReferencesGlobal();
                document.getElementById('pg-pocket-ref-voice-select').value = saved.id;
                document.getElementById('pg-pocket-ref-voice-select').dispatchEvent(new Event('change'));

                pocketSaveName.value = '';
                if (pocketRecorderCtrl) pocketRecorderCtrl.reset();
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

let _playgroundInitialized = false;

export function initPlayground() {
    if (_playgroundInitialized) return;
    _playgroundInitialized = true;

    const els = getElements();

    // Synthesizer pill switcher & installed status badges
    const installed = getInstalledSynthesizers();
    const pkgHint = {
        'f5-tts': 'f5',
        'pocket-tts': 'pocket',
        kokoro: 'kokoro',
        'qwen3-tts': 'qwen',
        supertonic: 'supertonic',
    };
    if (els.synthSelector) {
        els.synthSelector.querySelectorAll('.pg-synth-pill').forEach(btn => {
            const synthKey = btn.getAttribute('data-synth');
            const isInstalled = installed[synthKey] !== false;
            if (!isInstalled) {
                btn.disabled = true;
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
                const extra = pkgHint[synthKey] || synthKey;
                btn.title = `Not installed — run: uv add "epuboverlay[${extra}]"`;
            }
            btn.addEventListener('click', () => {
                if (btn.disabled) return;
                switchSynth(synthKey, els);
            });
        });
    }

    // Default: show preferred installed synthesizer panel
    switchSynth(getPreferredInstalledSynthesizer('dummy'), els);

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
        dialogueVoiceSelect: els.pocketDialogueVoiceSelect,
    });

    // Qwen3 mode & pills handler
    function syncPlaygroundQwenMode(m) {
        if (els.qwenVoiceModeSelector) {
            els.qwenVoiceModeSelector.querySelectorAll('.mode-pill').forEach(p => {
                p.classList.toggle('active', p.getAttribute('data-mode') === m);
            });
        }
        if (els.qwenModeSelect && els.qwenModeSelect.value !== m) {
            els.qwenModeSelect.value = m;
        }
        if (els.qwenModelSelect) {
            if (m === 'voice_design') {
                els.qwenModelSelect.value = 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign';
            } else if (m === 'clone' && !els.qwenModelSelect.value.includes('Base')) {
                els.qwenModelSelect.value = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base';
            } else if (m === 'custom_voice') {
                els.qwenModelSelect.value = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice';
            }
        }
        updatePlaygroundClonePanelVisibility(els);
    }

    if (els.qwenVoiceModeSelector) {
        els.qwenVoiceModeSelector.querySelectorAll('.mode-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                syncPlaygroundQwenMode(pill.getAttribute('data-mode') || 'custom_voice');
            });
        });
    }
    if (els.qwenModeSelect) {
        els.qwenModeSelect.addEventListener('change', () => {
            syncPlaygroundQwenMode(els.qwenModeSelect.value);
        });
    }

    // Keep quick-select saved voice dropdowns in sync with #pg-f5-ref-voice-select
    if (els.qwenRefVoiceSelect) {
        els.qwenRefVoiceSelect.addEventListener('change', () => {
            if (els.f5RefVoiceSelect && els.f5RefVoiceSelect.value !== els.qwenRefVoiceSelect.value) {
                els.f5RefVoiceSelect.value = els.qwenRefVoiceSelect.value;
                els.f5RefVoiceSelect.dispatchEvent(new Event('change'));
            }
        });
    }
    if (els.f5RefVoiceSelect) {
        els.f5RefVoiceSelect.addEventListener('change', () => {
            if (els.qwenRefVoiceSelect && els.qwenRefVoiceSelect.value !== els.f5RefVoiceSelect.value) {
                els.qwenRefVoiceSelect.value = els.f5RefVoiceSelect.value;
            }
        });
    }

    // Scenario Director Grid in Playground
    const pgScenarioGrid = document.getElementById('pg-scenario-grid');
    if (pgScenarioGrid) {
        pgScenarioGrid.querySelectorAll('.scenario-card').forEach(card => {
            card.addEventListener('click', () => {
                const key = card.getAttribute('data-scenario') || 'custom';
                pgScenarioGrid.querySelectorAll('.scenario-card').forEach(c => c.classList.toggle('active', c === card));
                const prof = SCENARIO_PROFILES[key];
                if (!prof) return;
                if (els.speedInput) els.speedInput.value = prof.speed;
                if (els.pocketTempInput) els.pocketTempInput.value = prof.temp;
                if (els.pocketLsdInput) els.pocketLsdInput.value = prof.lsd_decode_steps;
                if (els.pocketNoiseClampInput) els.pocketNoiseClampInput.value = prof.noise_clamp !== undefined ? prof.noise_clamp : '';
                if (els.pocketEosInput) els.pocketEosInput.value = prof.eos_threshold;
                if (els.pocketFramesEosInput) els.pocketFramesEosInput.value = prof.frames_after_eos !== undefined ? prof.frames_after_eos : '';
                if (els.instructInput && prof.instruct !== undefined) els.instructInput.value = prof.instruct;
                showToast(`Audition scenario "${prof.label}" loaded.`, 'info');
            });
        });
    }

    // 8-Language Sample Text Switcher
    const langSampleBar = document.getElementById('pg-lang-sample-bar');
    if (langSampleBar && els.textArea) {
        langSampleBar.querySelectorAll('.lang-sample-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const lang = chip.getAttribute('data-lang') || 'en';
                langSampleBar.querySelectorAll('.lang-sample-chip').forEach(c => c.classList.toggle('active', c === chip));
                if (LANGUAGE_SAMPLES[lang]) {
                    els.textArea.value = LANGUAGE_SAMPLES[lang];
                }
                // Also auto-align language dropdowns where applicable
                if (els.pocketLanguageSelect) {
                    const pocketLangMap = { en: 'english', de: 'german_24l', es: 'spanish_24l' };
                    if (pocketLangMap[lang]) els.pocketLanguageSelect.value = pocketLangMap[lang];
                }
                if (els.qwenLanguageSelect) {
                    const qwenLangMap = {
                        en: 'English', ru: 'Russian', ko: 'Korean', ja: 'Japanese',
                        zh: 'Chinese', de: 'German', es: 'Spanish',
                    };
                    if (qwenLangMap[lang]) els.qwenLanguageSelect.value = qwenLangMap[lang];
                }
            });
        });
    }

    // Inline Prosody & Emotion Tag Inserter
    const prosodyBar = document.getElementById('pg-prosody-tag-bar');
    if (prosodyBar && els.textArea) {
        prosodyBar.querySelectorAll('.prosody-tag-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const tag = chip.getAttribute('data-tag') || '';
                const start = els.textArea.selectionStart ?? els.textArea.value.length;
                const end = els.textArea.selectionEnd ?? els.textArea.value.length;
                const before = els.textArea.value.slice(0, start);
                const after = els.textArea.value.slice(end);
                els.textArea.value = `${before}${tag}${after}`;
                els.textArea.focus();
                const cursor = start + tag.length;
                els.textArea.setSelectionRange(cursor, cursor);
            });
        });
    }

    // File upload zones
    setupUploadZone(els.pocketRefAudioZone, els.pocketRefAudioInput, els.pocketRefAudioName);
    setupUploadZone(els.f5RefAudioZone, els.f5RefAudioInput, els.f5RefAudioName);

    // Initialize mic recording source toggles and events
    initPlaygroundRecorders();

    // Synthesize button
    if (els.synthesizeBtn) {
        els.synthesizeBtn.onclick = () => handleSynthesize(els);
    }

    // Cancel button
    if (els.cancelBtn) {
        els.cancelBtn.onclick = () => {
            if (pgAbortController) {
                pgAbortController.abort();
            }
        };
    }

    // Clear Cache Button
    if (els.clearHistoryBtn) {
        els.clearHistoryBtn.onclick = async () => {
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
        };
    }

    // Load initial playground history stack
    refreshPlaygroundList();
}
