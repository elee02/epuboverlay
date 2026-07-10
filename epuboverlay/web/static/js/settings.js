import { fetchSettings, saveSettings, saveProfile, deleteProfile as deleteProfileApi } from './api.js';
import { showToast, escapeHtml } from './utils.js';
import { showConfirmModal } from './modal.js';

let currentSettings = { custom_lexicon: [] };
let profiles = {};

export async function initSettings() {
    await loadSettingsData();
    setupSettingsHandlers();
}

async function loadSettingsData() {
    try {
        const data = await fetchSettings();
        currentSettings = data.current_settings || { custom_lexicon: [] };
        if (!currentSettings.custom_lexicon) {
            currentSettings.custom_lexicon = [];
        }
        profiles = data.profiles || {};
        
        applySettingsToUI(currentSettings);
        populateProfilesDropdown(profiles);
        renderLexiconTable(currentSettings.custom_lexicon);
    } catch (err) {
        showToast('Failed to load settings: ' + err.message, 'error');
    }
}

function applySettingsToUI(settings) {
    document.getElementById('setting-expand-numerals').checked = !!settings.expand_numerals;
    document.getElementById('setting-resolve-contractions').checked = !!settings.resolve_contractions;
    document.getElementById('setting-resolve-heteronyms').checked = !!settings.resolve_heteronyms;
    document.getElementById('setting-harmonize-punctuation').checked = !!settings.harmonize_punctuation;

    document.getElementById('default-synthesizer').value = settings.synthesizer || 'f5-tts';
    document.getElementById('default-device').value = settings.device || '';
    document.getElementById('default-speed').value = settings.speed || 1.0;
    document.getElementById('default-max-chars').value = settings.max_chars || 150;
    document.getElementById('default-concurrency').value = settings.concurrency || 2;
    document.getElementById('default-frame-rate').value = settings.frame_rate || 24000.0;
}

function getSettingsFromUI() {
    return {
        expand_numerals: document.getElementById('setting-expand-numerals').checked,
        resolve_contractions: document.getElementById('setting-resolve-contractions').checked,
        resolve_heteronyms: document.getElementById('setting-resolve-heteronyms').checked,
        harmonize_punctuation: document.getElementById('setting-harmonize-punctuation').checked,
        synthesizer: document.getElementById('default-synthesizer').value,
        device: document.getElementById('default-device').value,
        speed: parseFloat(document.getElementById('default-speed').value) || 1.0,
        max_chars: parseInt(document.getElementById('default-max-chars').value) || 150,
        concurrency: parseInt(document.getElementById('default-concurrency').value) || 2,
        frame_rate: parseFloat(document.getElementById('default-frame-rate').value) || 24000.0,
        custom_lexicon: currentSettings.custom_lexicon || [],
        // Retain existing voice selection properties if present
        voice: currentSettings.voice || 'af_heart',
        voice_formula: currentSettings.voice_formula || '',
        lang_code: currentSettings.lang_code || 'a',
    };
}

function populateProfilesDropdown(profilesMap) {
    const select = document.getElementById('profile-select');
    if (!select) return;
    
    select.innerHTML = '<option value="">-- Load a Profile --</option>';
    Object.keys(profilesMap).sort().forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });
}

function renderLexiconTable(lexicon) {
    const tbody = document.querySelector('#lexicon-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    if (lexicon.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted); padding: 1.5rem 1rem;">No entries in lexicon. Add words below.</td></tr>`;
        return;
    }
    
    lexicon.forEach((entry, index) => {
        const row = document.createElement('tr');
        row.style.borderBottom = '1px solid var(--border-subtle)';
        row.innerHTML = `
            <td style="padding: 0.6rem 0.8rem; font-family: monospace;">${escapeHtml(entry.word)}</td>
            <td style="padding: 0.6rem 0.8rem; font-family: monospace;">${escapeHtml(entry.replacement)}</td>
            <td style="padding: 0.6rem 0.8rem; text-align: center;">
                <button type="button" class="btn btn-danger btn-xs delete-lexicon-btn" data-index="${index}" style="line-height: 1; padding: 0.2rem 0.4rem;">✕</button>
            </td>
        `;
        row.querySelector('.delete-lexicon-btn').addEventListener('click', () => {
            currentSettings.custom_lexicon.splice(index, 1);
            renderLexiconTable(currentSettings.custom_lexicon);
        });
        tbody.appendChild(row);
    });
}

function setupSettingsHandlers() {
    // Save Settings
    const saveBtn = document.getElementById('settings-save-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            const updated = getSettingsFromUI();
            try {
                saveBtn.disabled = true;
                saveBtn.textContent = 'Saving...';
                await saveSettings(updated);
                currentSettings = updated;
                showToast('Global settings saved successfully!', 'success');
            } catch (err) {
                showToast('Failed to save settings: ' + err.message, 'error');
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = '💾 Save All Settings';
            }
        });
    }

    // Reset Defaults
    const resetBtn = document.getElementById('settings-reset-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            const defaults = {
                expand_numerals: true,
                resolve_contractions: true,
                resolve_heteronyms: true,
                harmonize_punctuation: true,
                synthesizer: 'f5-tts',
                device: '',
                speed: 1.0,
                max_chars: 150,
                concurrency: 2,
                frame_rate: 24000.0,
                custom_lexicon: []
            };
            applySettingsToUI(defaults);
            currentSettings.custom_lexicon = [];
            renderLexiconTable([]);
            showToast('Form reset to default values.', 'info');
        });
    }

    // Add Lexicon Word
    const addWordBtn = document.getElementById('lexicon-add-btn');
    const wordInput = document.getElementById('lexicon-add-word');
    const replacementInput = document.getElementById('lexicon-add-replacement');
    
    if (addWordBtn && wordInput && replacementInput) {
        addWordBtn.addEventListener('click', () => {
            const word = wordInput.value.trim();
            const replacement = replacementInput.value.trim();
            
            if (!word || !replacement) {
                showToast('Both original word and replacement pronunciation are required.', 'error');
                return;
            }
            
            if (currentSettings.custom_lexicon.some(e => e.word.toLowerCase() === word.toLowerCase())) {
                showToast('Word already exists in lexicon.', 'error');
                return;
            }
            
            currentSettings.custom_lexicon.push({ word, replacement });
            renderLexiconTable(currentSettings.custom_lexicon);
            
            wordInput.value = '';
            replacementInput.value = '';
            showToast(`Added rule: "${word}" ➔ "${replacement}"`, 'success');
        });
    }

    // Load Profile
    const loadProfileBtn = document.getElementById('load-profile-btn');
    const profileSelect = document.getElementById('profile-select');
    if (loadProfileBtn && profileSelect) {
        loadProfileBtn.addEventListener('click', () => {
            const selected = profileSelect.value;
            if (!selected) {
                showToast('Please select a profile to load.', 'error');
                return;
            }
            
            const profileSettings = profiles[selected];
            if (profileSettings) {
                currentSettings = { ...profileSettings };
                if (!currentSettings.custom_lexicon) {
                    currentSettings.custom_lexicon = [];
                }
                applySettingsToUI(currentSettings);
                renderLexiconTable(currentSettings.custom_lexicon);
                showToast(`Loaded profile "${selected}". Click "Save All Settings" to apply globally.`, 'success');
            }
        });
    }

    // Save Profile
    const saveProfileBtn = document.getElementById('save-profile-btn');
    const newProfileInput = document.getElementById('new-profile-name');
    if (saveProfileBtn && newProfileInput) {
        saveProfileBtn.addEventListener('click', async () => {
            const name = newProfileInput.value.trim();
            if (!name) {
                showToast('Please enter a name for the new profile.', 'error');
                return;
            }
            
            const settings = getSettingsFromUI();
            try {
                saveProfileBtn.disabled = true;
                await saveProfile(name, settings);
                newProfileInput.value = '';
                await loadSettingsData(); // Refresh list
                showToast(`Profile "${name}" saved successfully!`, 'success');
            } catch (err) {
                showToast('Failed to save profile: ' + err.message, 'error');
            } finally {
                saveProfileBtn.disabled = false;
            }
        });
    }

    // Delete Profile
    const deleteProfileBtn = document.getElementById('delete-profile-btn');
    if (deleteProfileBtn && profileSelect) {
        deleteProfileBtn.addEventListener('click', async () => {
            const selected = profileSelect.value;
            if (!selected) {
                showToast('Please select a profile to delete.', 'error');
                return;
            }
            
            const confirmed = await showConfirmModal(
                "Delete Profile",
                `Are you sure you want to permanently delete the profile "${selected}"?`,
                "Delete",
                "btn-danger"
            );
            if (!confirmed) return;
            
            try {
                await deleteProfileApi(selected);
                await loadSettingsData();
                showToast(`Deleted profile "${selected}".`, 'success');
            } catch (err) {
                showToast('Failed to delete profile: ' + err.message, 'error');
            }
        });
    }
}
