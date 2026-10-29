/**
 * references.js — Centralized management of user's saved reference voice library.
 */

import { fetchReferences } from './api.js?v=8';
import { showToast } from './utils.js?v=8';

export let savedReferences = [];

export function populateReferencesDropdowns() {
    const selects = [
        { el: document.getElementById('ref-voice-select'), type: 'f5' },
        { el: document.getElementById('pocket-ref-voice-select'), type: 'pocket' },
        { el: document.getElementById('pg-f5-ref-voice-select'), type: 'f5' },
        { el: document.getElementById('pg-pocket-ref-voice-select'), type: 'pocket' },
        { el: document.getElementById('pg-qwen-ref-voice-select'), type: 'qwen' },
        { el: document.getElementById('pg-fish-ref-voice-select'), type: 'fish' },
    ];
    selects.forEach(({ el }) => {
        if (!el) return;
        const firstOpt = el.options[0] || new Option('-- Upload Custom Audio --', '');
        el.innerHTML = '';
        el.appendChild(firstOpt);

        savedReferences.forEach(ref => {
            const opt = document.createElement('option');
            opt.value = ref.id;
            opt.textContent = ref.name;
            el.appendChild(opt);
        });
    });
}

export async function loadSavedReferencesGlobal() {
    try {
        savedReferences = await fetchReferences();
        populateReferencesDropdowns();
    } catch (err) {
        showToast('Failed to load reference voices: ' + err.message, 'error');
    }
}
