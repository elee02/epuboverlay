/**
 * pocket.js — PocketTTS voice mode UI helpers.
 *
 * Manages the Preset / Clone toggle for PocketTTS panels in both
 * the Generate form and the Voice Playground.
 */

import { showToast } from './utils.js';

export const POCKET_VOICE_NAMES = {
    alba: 'Alba (Default Female)',
    marius: 'Marius (Male)',
    javert: 'Javert (Male, Commanding)',
    jean: 'Jean (Male, Warm)',
    fantine: 'Fantine (Female, Soft)',
    cosette: 'Cosette (Female, Bright)',
    eponine: 'Eponine (Female, Expressive)',
    azelma: 'Azelma (Female)',
    anna: 'Anna (Female)',
    vera: 'Vera (Female)',
    charles: 'Charles (Male)',
    paul: 'Paul (Male)',
    george: 'George (Male)',
    mary: 'Mary (Female)',
    jane: 'Jane (Female)',
    michael: 'Michael (Male)',
    eve: 'Eve (Female)',
};

export let pocketVoices = [];

export function setPocketVoices(voices) {
    pocketVoices = voices;
}

/**
 * Populate a <select> element with PocketTTS preset voice options.
 * @param {HTMLSelectElement} selectEl
 * @param {string} [selected] - Voice to pre-select
 */
export function populatePocketVoiceSelect(selectEl, selected = 'alba') {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    const list = pocketVoices.length ? pocketVoices : Object.keys(POCKET_VOICE_NAMES);
    list.forEach(voice => {
        const opt = document.createElement('option');
        opt.value = voice;
        opt.textContent = POCKET_VOICE_NAMES[voice] || voice;
        if (voice === selected) opt.selected = true;
        selectEl.appendChild(opt);
    });
}

/**
 * Set up the Preset / Clone mode toggle for a PocketTTS section.
 *
 * @param {object} elements - DOM element references for this section
 * @param {HTMLElement} elements.modeSelector  - Container with [data-mode] buttons
 * @param {HTMLElement} elements.presetPanel   - Panel shown in preset mode
 * @param {HTMLElement} elements.clonePanel    - Panel shown in clone mode
 * @param {HTMLSelectElement} elements.voiceSelect - <select> for preset voices
 * @param {string} [initialMode='preset']
 */
export function setupPocketModeToggle(elements, initialMode = 'preset') {
    const { modeSelector, presetPanel, clonePanel, voiceSelect } = elements;

    if (voiceSelect) {
        populatePocketVoiceSelect(voiceSelect);
    }

    function applyMode(mode) {
        if (modeSelector) {
            modeSelector.querySelectorAll('.mode-pill').forEach(btn => {
                btn.classList.toggle('active', btn.getAttribute('data-mode') === mode);
            });
        }
        if (presetPanel) presetPanel.style.display = mode === 'preset' ? 'block' : 'none';
        if (clonePanel)  clonePanel.style.display  = mode === 'clone'  ? 'block' : 'none';
    }

    if (modeSelector) {
        modeSelector.querySelectorAll('.mode-pill').forEach(btn => {
            btn.addEventListener('click', () => applyMode(btn.getAttribute('data-mode')));
        });
    }

    applyMode(initialMode);
}

/**
 * Read the current PocketTTS voice selection from a set of elements.
 * Returns { mode: 'preset'|'clone', pocket_voice, ref_audio_file }.
 *
 * @param {object} elements
 * @param {HTMLElement} elements.modeSelector
 * @param {HTMLSelectElement} elements.voiceSelect
 * @param {HTMLInputElement} elements.refAudioInput
 */
export function getPocketVoiceParams(elements) {
    const { modeSelector, voiceSelect, refAudioInput } = elements;

    const activeBtn = modeSelector
        ? modeSelector.querySelector('.mode-pill.active')
        : null;
    const mode = activeBtn ? activeBtn.getAttribute('data-mode') : 'preset';

    if (mode === 'preset') {
        return {
            mode,
            pocket_voice: voiceSelect ? voiceSelect.value : '',
            ref_audio_file: null,
        };
    } else {
        const file = refAudioInput && refAudioInput.files[0] ? refAudioInput.files[0] : null;
        return {
            mode,
            pocket_voice: '',
            ref_audio_file: file,
        };
    }
}
