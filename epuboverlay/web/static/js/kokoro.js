import { previewVoice, fetchVoiceBlends, saveVoiceBlend, deleteVoiceBlend } from './api.js';
import { showToast } from './utils.js';

export let activeVoiceMode = 'single';
export let activeBlendVoices = [];
export let kokoroVoices = [];
export let previewAudio = null;
export let customVoiceBlends = [];

export function setKokoroVoices(voices) {
    kokoroVoices = voices;
}

export function resetBlendVoices() {
    activeBlendVoices = [];
}

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
    '#8b5cf6', '#06b6d4', '#10b981', '#f43f5e', '#f59e0b', '#3b82f6', '#f97316', '#a855f7'
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

export function getVoiceMetadata(voiceName) {
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
    
    let namePart = voiceName.substring(3);
    namePart = namePart.charAt(0).toUpperCase() + namePart.slice(1);
    
    return {
        id: voiceName,
        displayName: `${namePart} (${meta.name} ${meta.gender})`,
        langName: meta.name,
        gender: meta.gender
    };
}

export function updateFilteredVoices(elements = {}) {
    const langSelect = elements.langSelect || document.getElementById('lang-code-select');
    if (!langSelect) return;
    
    const langCode = langSelect.value;
    const showAllCheckbox = elements.showAllCheckbox || document.getElementById('show-all-languages-checkbox');
    const showAll = showAllCheckbox ? showAllCheckbox.checked : false;
    
    const prefixes = LANG_PREFIX_MAP[langCode] || [];
    
    const filtered = kokoroVoices.filter(voice => {
        if (showAll) return true;
        return prefixes.some(p => voice.startsWith(p));
    });
    
    // 1. Update Single Voice Selector
    const voiceSelect = elements.voiceSelect || document.getElementById('voice-select');
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
    const blendAddSelect = elements.blendAddSelect || document.getElementById('blend-add-select');
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

export function renderBlendMixer(elements = {}) {
    const bar = elements.blendVisualizerBar || document.getElementById('blend-visualizer-bar');
    const list = elements.blendChannelsList || document.getElementById('blend-channels-list');
    const formulaInput = elements.voiceFormulaInput || document.getElementById('voice-formula-input');
    
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
            renderBlendMixer(elements);
        });
        
        const removeBtn = row.querySelector('.blend-channel-remove');
        removeBtn.addEventListener('click', () => {
            activeBlendVoices.splice(index, 1);
            renderBlendMixer(elements);
            updateFilteredVoices(elements);
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

export function addVoiceToBlend(elements = {}) {
    const select = elements.blendAddSelect || document.getElementById('blend-add-select');
    if (!select) return;
    const voice = select.value;
    if (!voice) return;
    
    if (activeBlendVoices.some(v => v.voice === voice)) {
        showToast('Voice is already in the mix!', 'error');
        return;
    }
    
    activeBlendVoices.push({ voice, weight: 50 });
    
    renderBlendMixer(elements);
    updateFilteredVoices(elements);
}

export function applyPreset(formula, elements = {}) {
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
        setVoiceMode('blend', elements);
        renderBlendMixer(elements);
        updateFilteredVoices(elements);
        showToast('Preset applied successfully!', 'success');
    }
}

export async function loadCustomVoiceBlends() {
    try {
        const data = await fetchVoiceBlends();
        customVoiceBlends = data || [];
    } catch (err) {
        console.error('Failed to load custom voice blends:', err);
    }
}

export function renderPresets(elements = {}) {
    const grid = elements.blendPresetsGrid || document.getElementById('blend-presets-grid');
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
            applyPreset(preset.formula, elements);
        });
        grid.appendChild(card);
    });

    if (customVoiceBlends && customVoiceBlends.length > 0) {
        customVoiceBlends.forEach(preset => {
            const card = document.createElement('div');
            card.className = 'blend-preset-card custom-preset';
            card.style.position = 'relative';
            card.innerHTML = `
                <div class="blend-preset-title" style="padding-right: 1.5rem; font-weight: 600;">${preset.name} <span class="badge" style="background:#14b8a6; color:#fff; border:none; font-size:0.7rem; padding:0.1rem 0.3rem; border-radius:3px; margin-left:0.25rem;">Custom</span></div>
                <div class="blend-preset-desc">${preset.desc || 'Custom voice formula'}</div>
                <button type="button" class="delete-preset-btn" title="Delete Preset" style="position: absolute; top: 0.5rem; right: 0.5rem; background: none; border: none; color: #f43f5e; cursor: pointer; font-size: 0.9rem; padding: 0; line-height: 1;">✕</button>
            `;
            
            card.querySelector('.delete-preset-btn').addEventListener('click', async (e) => {
                e.stopPropagation();
                if (confirm(`Are you sure you want to delete the preset "${preset.name}"?`)) {
                    try {
                        await deleteVoiceBlend(preset.name);
                        showToast(`Deleted preset: ${preset.name}`, 'success');
                        await loadCustomVoiceBlends();
                        
                        // Refresh presets grids on ALL active views
                        const mainGrid = document.getElementById('blend-presets-grid');
                        const pgGrid = document.getElementById('pg-blend-presets-grid');
                        if (mainGrid) renderPresets({ blendPresetsGrid: mainGrid, voiceFormulaInput: document.getElementById('voice-formula-input') });
                        if (pgGrid) renderPresets({ blendPresetsGrid: pgGrid, voiceFormulaInput: document.getElementById('pg-voice-formula-input') });
                    } catch (err) {
                        showToast(err.message, 'error');
                    }
                }
            });
            
            card.addEventListener('click', () => {
                applyPreset(preset.formula, elements);
            });
            grid.appendChild(card);
        });
    }
}

export function setVoiceMode(mode, elements = {}) {
    activeVoiceMode = mode;
    
    const selector = elements.voiceModeSelector || document.getElementById('voice-mode-selector');
    if (selector) {
        selector.querySelectorAll('.mode-pill').forEach(btn => {
            if (btn.getAttribute('data-mode') === mode) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }
    
    const singlePanel = elements.kokoroSinglePanel || document.getElementById('kokoro-single-panel');
    const blendPanel = elements.kokoroBlendPanel || document.getElementById('kokoro-blend-panel');
    
    if (mode === 'single') {
        if (singlePanel) singlePanel.style.display = 'block';
        if (blendPanel) blendPanel.style.display = 'none';
    } else {
        if (singlePanel) singlePanel.style.display = 'none';
        if (blendPanel) blendPanel.style.display = 'block';
        
        if (activeBlendVoices.length === 0) {
            const voiceSelect = elements.voiceSelect || document.getElementById('voice-select');
            const defaultVoice = voiceSelect ? voiceSelect.value : 'af_heart';
            activeBlendVoices.push({ voice: defaultVoice || 'af_heart', weight: 100 });
            renderBlendMixer(elements);
        }
    }
}

export async function playVoicePreview(elements = {}) {
    const playBtn = elements.playPreviewBtn || document.getElementById('play-preview-btn');
    const textInput = elements.previewTextInput || document.getElementById('preview-text-input');
    const langSelect = elements.langSelect || document.getElementById('lang-code-select');
    
    if (!playBtn) return;
    
    if (previewAudio && !previewAudio.paused) {
        previewAudio.pause();
        previewAudio = null;
        updatePreviewButtonState(false, playBtn);
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
        const voiceSelect = elements.voiceSelect || document.getElementById('voice-select');
        voice = voiceSelect ? voiceSelect.value : '';
        if (!voice) {
            showToast('Please select a voice to preview.', 'error');
            return;
        }
    } else {
        const formulaInput = elements.voiceFormulaInput || document.getElementById('voice-formula-input');
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
        
        const blob = await previewVoice(body);
        const url = URL.createObjectURL(blob);
        
        previewAudio = new Audio(url);
        previewAudio.addEventListener('ended', () => {
            updatePreviewButtonState(false, playBtn);
            previewAudio = null;
        });
        
        previewAudio.addEventListener('pause', () => {
            updatePreviewButtonState(false, playBtn);
        });
        
        updatePreviewButtonState(true, playBtn);
        playBtn.disabled = false;
        await previewAudio.play();
        
    } catch (err) {
        showToast(err.message || 'Failed to play preview.', 'error');
        updatePreviewButtonState(false, playBtn);
        playBtn.disabled = false;
    }
}

export function updatePreviewButtonState(isPlaying, playBtn) {
    playBtn = playBtn || document.getElementById('play-preview-btn');
    if (!playBtn) return;
    
    if (isPlaying) {
        playBtn.textContent = '⏹ Stop Preview';
        playBtn.classList.add('btn-preview-playing');
    } else {
        playBtn.textContent = '🔊 Play Preview';
        playBtn.classList.remove('btn-preview-playing');
    }
}

export async function setupKokoroMixer(elements = {}) {
    const modeSelector = elements.voiceModeSelector || document.getElementById('voice-mode-selector');
    const langSelect = elements.langSelect || document.getElementById('lang-code-select');
    const showAllCheckbox = elements.showAllCheckbox || document.getElementById('show-all-languages-checkbox');
    const addBtn = elements.addToBlendBtn || document.getElementById('add-to-blend-btn');
    const resetBtn = elements.formulaResetBtn || document.getElementById('formula-reset-btn');
    const previewBtn = elements.playPreviewBtn || document.getElementById('play-preview-btn');
    const saveBtn = elements.saveBlendBtn || document.getElementById('save-blend-btn');
    
    if (modeSelector) {
        modeSelector.querySelectorAll('.mode-pill').forEach(btn => {
            btn.addEventListener('click', () => {
                setVoiceMode(btn.getAttribute('data-mode'), elements);
            });
        });
    }
    
    if (langSelect) {
        langSelect.addEventListener('change', () => {
            updateFilteredVoices(elements);
        });
    }
    
    if (showAllCheckbox) {
        showAllCheckbox.addEventListener('change', () => {
            updateFilteredVoices(elements);
        });
    }
    
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            addVoiceToBlend(elements);
        });
    }
    
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            activeBlendVoices.length = 0;
            renderBlendMixer(elements);
            updateFilteredVoices(elements);
            showToast('Mix reset successfully.', 'success');
        });
    }
    
    if (previewBtn) {
        previewBtn.addEventListener('click', () => {
            playVoicePreview(elements);
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            const formulaInput = elements.voiceFormulaInput || document.getElementById('voice-formula-input');
            const formula = formulaInput ? formulaInput.value.trim() : '';
            if (!formula) {
                showToast('Please mix some voices to save a blend.', 'error');
                return;
            }
            
            const name = prompt('Enter a name for your custom voice blend:');
            if (name === null) return;
            const cleanName = name.trim();
            if (!cleanName) {
                showToast('Blend name cannot be empty.', 'error');
                return;
            }
            
            const desc = prompt('Enter a brief description (optional):', 'Custom voice formula');
            if (desc === null) return;
            
            try {
                const oldText = saveBtn.textContent;
                saveBtn.textContent = 'Saving...';
                await saveVoiceBlend({
                    name: cleanName,
                    desc: desc.trim(),
                    formula: formula
                });
                showToast(`Saved blend "${cleanName}"!`, 'success');
                await loadCustomVoiceBlends();
                
                const mainGrid = document.getElementById('blend-presets-grid');
                const pgGrid = document.getElementById('pg-blend-presets-grid');
                if (mainGrid) renderPresets({ blendPresetsGrid: mainGrid, voiceFormulaInput: document.getElementById('voice-formula-input') });
                if (pgGrid) renderPresets({ blendPresetsGrid: pgGrid, voiceFormulaInput: document.getElementById('pg-voice-formula-input') });
                saveBtn.textContent = oldText;
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    }
    
    await loadCustomVoiceBlends();
    renderPresets(elements);
}
