export const toastContainer = document.getElementById('toast-container');

let _installedSynthesizers = {
    'dummy': true,
    'kokoro': true,
    'pocket-tts': true,
    'qwen3-tts': true,
    'fish-speech': true,
    'f5-tts': true,
};

export const SCENARIO_PROFILES = {
    custom: {
        label: 'Custom Studio',
        speed: 1.0,
        max_chars: 150,
        temp: 0.7,
        lsd_decode_steps: 1,
        noise_clamp: '',
        eos_threshold: -4.0,
        frames_after_eos: '',
        instruct: '',
        emotion_tag: '',
    },
    fiction_audiobook: {
        label: 'Fiction & Literary',
        speed: 0.96,
        max_chars: 165,
        temp: 0.78,
        lsd_decode_steps: 2,
        noise_clamp: '',
        eos_threshold: -4.2,
        frames_after_eos: 5,
        instruct: 'Speak in a warm, captivating storytelling tone with expressive cadence and natural breath pauses.',
        emotion_tag: '(soft tone)',
    },
    technical_docs: {
        label: 'Technical & Academic',
        speed: 1.02,
        max_chars: 135,
        temp: 0.55,
        lsd_decode_steps: 2,
        noise_clamp: 2.5,
        eos_threshold: -4.0,
        frames_after_eos: 3,
        instruct: 'Speak in a clear, calm, articulate, and measured instructional tone with crisp pronunciation.',
        emotion_tag: '(calm)',
    },
    executive_briefing: {
        label: 'Executive Briefing',
        speed: 1.12,
        max_chars: 180,
        temp: 0.62,
        lsd_decode_steps: 1,
        noise_clamp: 3.0,
        eos_threshold: -3.8,
        frames_after_eos: 1,
        instruct: 'Speak with confident, brisk, authoritative broadcast clarity and energetic pacing.',
        emotion_tag: '(serious)',
    },
    language_learning: {
        label: 'Language Shadowing',
        speed: 0.86,
        max_chars: 105,
        temp: 0.5,
        lsd_decode_steps: 3,
        noise_clamp: 2.2,
        eos_threshold: -4.5,
        frames_after_eos: 7,
        instruct: 'Speak slowly and distinctly with crystal-clear phonetic articulation for language learners.',
        emotion_tag: '(calm)',
    },
    dramatic_dialogue: {
        label: 'Dramatic Dialogue',
        speed: 0.95,
        max_chars: 145,
        temp: 0.85,
        lsd_decode_steps: 3,
        noise_clamp: '',
        eos_threshold: -4.2,
        frames_after_eos: 4,
        instruct: 'Deliver with rich dramatic emotion, dynamic pitch variation, and vivid character expression.',
        emotion_tag: '(empathetic)',
    },
};

export function setInstalledSynthesizers(installedMap) {
    if (installedMap && typeof installedMap === 'object') {
        _installedSynthesizers = { ..._installedSynthesizers, ...installedMap };
    }
}

export function getInstalledSynthesizers() {
    return _installedSynthesizers;
}

export function getPreferredInstalledSynthesizer(fallback = 'dummy') {
    for (const key of ['pocket-tts', 'kokoro', 'qwen3-tts', 'fish-speech', 'f5-tts', 'dummy']) {
        if (_installedSynthesizers[key]) return key;
    }
    return fallback;
}

export function applyInstalledSynthesizersToSelect(selectEl, installedMap = _installedSynthesizers) {
    if (!selectEl || !installedMap) return;
    const pkgHint = {
        'f5-tts': 'f5',
        'pocket-tts': 'pocket',
        'kokoro': 'kokoro',
        'qwen3-tts': 'qwen',
        'fish-speech': 'fish',
    };
    Array.from(selectEl.options).forEach(opt => {
        const val = opt.value;
        if (!opt.dataset.baseLabel) {
            opt.dataset.baseLabel = opt.textContent.replace(/\s*\(Not Installed.*\)$/i, '');
        }
        const isInstalled = installedMap[val] !== false;
        opt.disabled = !isInstalled;
        if (isInstalled) {
            opt.textContent = opt.dataset.baseLabel;
        } else {
            const extra = pkgHint[val] || val;
            opt.textContent = `${opt.dataset.baseLabel} (Not Installed — uv sync --extra ${extra})`;
        }
    });
    if (selectEl.selectedOptions.length && selectEl.selectedOptions[0].disabled) {
        const firstEnabled = Array.from(selectEl.options).find(o => !o.disabled);
        if (firstEnabled) {
            selectEl.value = firstEnabled.value;
        }
    }
}

export function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { success: '✓', error: '✗', info: 'ℹ' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> <span>${escapeHtml(String(message ?? ''))}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

export function formatTime(seconds) {
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

export function formatPlayerTime(secs) {
    if (!isFinite(secs) || isNaN(secs) || secs < 0) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

export function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

/**
 * Shared controller for Export Audiobook + Subtitles form and Completed Job cards.
 */
export function setupExportCheckboxDependencies({
    audioFmtSelect,
    mp4Cb,
    mp4Group,
    embedSubsCb,
    embedSubsGroup,
    fmtAss,
    fmtSrt,
    fmtVtt,
    fmtTtml,
    fmtSbv,
    fmtLrc,
    fmtTxt,
    mergeCb,
    centerCb,
    submitBtn,
    coverInput,
    coverContainer,
    coverNameEl,
}) {
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

    function update() {
        const audioFmt = audioFmtSelect ? audioFmtSelect.value : 'm4b';
        const audioChecked = audioFmt !== 'none';
        const mp4Checked = mp4Cb ? mp4Cb.checked : false;

        if (mp4Cb) {
            if (audioChecked) {
                mp4Cb.disabled = false;
                if (mp4Group) mp4Group.style.opacity = '1';
                if (embedSubsCb) {
                    embedSubsCb.disabled = !mp4Checked;
                    if (embedSubsGroup) embedSubsGroup.style.opacity = mp4Checked ? '1' : '0.5';
                    if (!mp4Checked) embedSubsCb.checked = false;
                }
            } else {
                mp4Cb.disabled = true;
                mp4Cb.checked = false;
                if (mp4Group) mp4Group.style.opacity = '0.5';
                if (embedSubsCb) {
                    embedSubsCb.disabled = true;
                    embedSubsCb.checked = false;
                    if (embedSubsGroup) embedSubsGroup.style.opacity = '0.5';
                }
            }
        }

        const isMp4 = mp4Cb ? mp4Cb.checked : false;
        const isEmbed = embedSubsCb ? embedSubsCb.checked : false;

        // Subtitle formats are supported alongside M4B, M4A, MP4, or standalone ("none").
        // Only LRC is disabled when MP4 video is selected since LRC cannot be muxed as video subtitles.
        setFmtState(fmtAss, true);
        setFmtState(fmtSrt, true);
        setFmtState(fmtVtt, true);
        setFmtState(fmtTtml, true);
        setFmtState(fmtSbv, true);
        setFmtState(fmtLrc, !isMp4);
        setFmtState(fmtTxt, true);

        const anyFmtChecked = [fmtAss, fmtSrt, fmtVtt, fmtTtml, fmtSbv, fmtLrc, fmtTxt].some(
            el => el && el.checked && !el.disabled
        );
        const audioOrAnyFmtSelected = audioChecked || anyFmtChecked;

        if (mergeCb) {
            mergeCb.disabled = !audioOrAnyFmtSelected;
            const mergeLabel = mergeCb.closest('label');
            if (mergeLabel) mergeLabel.style.opacity = audioOrAnyFmtSelected ? '1' : '0.5';
            if (!audioOrAnyFmtSelected) mergeCb.checked = false;
        }

        const centerApplicableChecked =
            isEmbed || [fmtAss, fmtSrt, fmtVtt, fmtTtml, fmtSbv].some(el => el && el.checked && !el.disabled);
        if (centerCb) {
            centerCb.disabled = !centerApplicableChecked;
            const centerLabel = centerCb.closest('label');
            if (centerLabel) centerLabel.style.opacity = centerApplicableChecked ? '1' : '0.5';
            if (!centerApplicableChecked) centerCb.checked = false;
        }

        if (submitBtn) {
            submitBtn.disabled = !audioOrAnyFmtSelected;
        }

        if (coverInput) {
            const enableCover = audioFmt === 'm4b';
            coverInput.disabled = !enableCover;
            if (coverContainer) {
                coverContainer.style.opacity = enableCover ? '1' : '0.5';
                coverContainer.style.pointerEvents = enableCover ? 'auto' : 'none';
            }
            if (!enableCover) {
                coverInput.value = '';
                if (coverNameEl) {
                    coverNameEl.style.display = 'none';
                    coverNameEl.textContent = '';
                }
            }
        }
    }

    if (audioFmtSelect && mp4Cb) {
        audioFmtSelect.addEventListener('change', update);
        mp4Cb.addEventListener('change', update);
        if (embedSubsCb) {
            embedSubsCb.addEventListener('change', () => {
                if (embedSubsCb.checked && centerCb) {
                    centerCb.checked = true;
                }
                update();
            });
        }
        [fmtAss, fmtSrt, fmtVtt, fmtTtml, fmtSbv, fmtLrc, fmtTxt].forEach(el => {
            if (el) el.addEventListener('change', update);
        });
        update();
    }

    return update;
}

/**
 * Convert an AudioBuffer to a 16-bit PCM RIFF WAV Blob.
 */
function encodeAudioBufferToWavBlob(audioBuffer) {
    const numChannels = 1;
    const sampleRate = audioBuffer.sampleRate;
    const channelData = audioBuffer.getChannelData(0);
    const numSamples = channelData.length;
    const buffer = new ArrayBuffer(44 + numSamples * 2);
    const view = new DataView(buffer);

    function writeStr(offset, str) {
        for (let i = 0; i < str.length; i++) {
            view.setUint8(offset + i, str.charCodeAt(i));
        }
    }

    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + numSamples * 2, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * 2, true);
    view.setUint16(32, numChannels * 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, numSamples * 2, true);

    let offset = 44;
    for (let i = 0; i < numSamples; i++) {
        const s = Math.max(-1, Math.min(1, channelData[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        offset += 2;
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

/**
 * Decode a browser MediaRecorder blob (WebM/Ogg/MP4) into a standard RIFF WAV Blob.
 */
export async function convertRecordedBlobToWav(rawBlob) {
    try {
        const arrayBuffer = await rawBlob.arrayBuffer();
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return rawBlob;
        const audioCtx = new AudioCtx();
        try {
            const decoded = await audioCtx.decodeAudioData(arrayBuffer);
            return encodeAudioBufferToWavBlob(decoded);
        } finally {
            if (audioCtx.close) await audioCtx.close();
        }
    } catch (_err) {
        return rawBlob;
    }
}

/**
 * Shared microphone recorder setup for Voice Playground & Voice Library.
 */
export function setupAudioRecorder(containerSelector, onBlobRecorded) {
    const container = typeof containerSelector === 'string'
        ? document.querySelector(containerSelector)
        : containerSelector;
    if (!container) return null;

    const startBtn = container.querySelector('.rec-btn-start');
    const stopBtn = container.querySelector('.rec-btn-stop');
    const statusEl = container.querySelector('.rec-status');
    const timerEl = container.querySelector('.rec-timer');
    const previewEl = container.querySelector('.rec-audio-preview');
    const saveBox = container.querySelector('.rec-preview-group');

    if (!startBtn || !stopBtn || !statusEl || !timerEl || !previewEl) return null;

    let mediaRecorder = null;
    let chunks = [];
    let recordTimer = null;
    let recordSeconds = 0;

    startBtn.addEventListener('click', async () => {
        chunks = [];
        recordSeconds = 0;
        timerEl.textContent = '00:00';
        statusEl.textContent = 'Recording...';
        if (statusEl.previousElementSibling) statusEl.previousElementSibling.classList.add('pulsing');
        previewEl.style.display = 'none';
        if (saveBox) saveBox.style.display = 'none';
        if (onBlobRecorded) onBlobRecorded(null);

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.ondataavailable = e => {
                if (e.data.size > 0) chunks.push(e.data);
            };
            mediaRecorder.onstop = async () => {
                const rawBlob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
                const wavBlob = await convertRecordedBlobToWav(rawBlob);
                previewEl.src = URL.createObjectURL(wavBlob);
                previewEl.style.display = 'block';
                if (saveBox) saveBox.style.display = 'flex';
                statusEl.textContent = 'Recording completed';
                if (statusEl.previousElementSibling) statusEl.previousElementSibling.classList.remove('pulsing');
                stream.getTracks().forEach(track => track.stop());
                if (onBlobRecorded) onBlobRecorded(wavBlob);
            };
            mediaRecorder.start();
            startBtn.disabled = true;
            stopBtn.disabled = false;

            recordTimer = setInterval(() => {
                recordSeconds++;
                const m = Math.floor(recordSeconds / 60).toString().padStart(2, '0');
                const s = (recordSeconds % 60).toString().padStart(2, '0');
                timerEl.textContent = `${m}:${s}`;
            }, 1000);
        } catch (err) {
            showToast('Could not access microphone: ' + err.message, 'error');
            statusEl.textContent = 'Microphone error';
            if (statusEl.previousElementSibling) statusEl.previousElementSibling.classList.remove('pulsing');
        }
    });

    stopBtn.addEventListener('click', () => {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
            clearInterval(recordTimer);
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }
    });

    return {
        reset() {
            if (saveBox) saveBox.style.display = 'none';
            previewEl.src = '';
            previewEl.style.display = 'none';
            timerEl.textContent = '00:00';
            statusEl.textContent = 'Ready to record';
            if (onBlobRecorded) onBlobRecorded(null);
        }
    };
}
