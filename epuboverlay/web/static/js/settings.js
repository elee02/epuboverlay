import {
    fetchSettings,
    saveSettings,
    fetchReferences,
    saveReference,
    deleteReference,
    updateReference,
    testFishConnection,
} from './api.js?v=8';
import {
    showToast,
    escapeHtml,
    applyInstalledSynthesizersToSelect,
    getPreferredInstalledSynthesizer,
    setupAudioRecorder,
} from './utils.js?v=8';
import { showConfirmModal } from './modal.js?v=8';
import { loadSavedReferencesGlobal } from './references.js?v=8';

let currentSettings = { custom_lexicon: [] };

export async function initSettings() {
    setupTabs();
    await loadSettingsData();
    setupSettingsHandlers();
    setupVoiceLibraryHandlers();
    await refreshVoiceLibraryList();
}

// ── Tab Switching ────────────────────────────────────────────────────────────

function setupTabs() {
    const tabButtons = document.querySelectorAll('.settings-tab-btn');
    const tabContents = document.querySelectorAll('.settings-tab-content');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.getAttribute('data-tab');
            tabButtons.forEach(b => {
                b.classList.toggle('active', b === btn);
                b.classList.toggle('btn-ghost', b !== btn);
            });
            tabContents.forEach(content => {
                const id = content.getAttribute('id');
                content.style.display = id === `settings-tab-content-${tabName}` ? 'block' : 'none';
            });
        });
    });
}

// ── Settings (Defaults & Normalization) ──────────────────────────────────────

async function loadSettingsData() {
    try {
        const data = await fetchSettings();
        currentSettings = data.current_settings || { custom_lexicon: [] };
        if (!currentSettings.custom_lexicon) {
            currentSettings.custom_lexicon = [];
        }
        applySettingsToUI(currentSettings);
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

    const defaultSynthEl = document.getElementById('default-synthesizer');
    if (defaultSynthEl) {
        defaultSynthEl.value = settings.synthesizer || getPreferredInstalledSynthesizer('dummy');
        applyInstalledSynthesizersToSelect(defaultSynthEl);
    }
    document.getElementById('default-device').value = settings.device || '';
    document.getElementById('default-speed').value = settings.speed || 1.0;
    document.getElementById('default-max-chars').value = settings.max_chars || 150;
    document.getElementById('default-concurrency').value = settings.concurrency || 2;
    document.getElementById('default-frame-rate').value = settings.frame_rate || 24000.0;
    const fishKeyEl = document.getElementById('default-fish-api-key');
    if (fishKeyEl) fishKeyEl.value = settings.fish_api_key || '';
    const fishUrlEl = document.getElementById('default-fish-api-url');
    if (fishUrlEl) fishUrlEl.value = settings.fish_api_url || '';
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
        fish_api_key: document.getElementById('default-fish-api-key')?.value.trim() || '',
        fish_api_url: document.getElementById('default-fish-api-url')?.value.trim() || '',
        custom_lexicon: currentSettings.custom_lexicon || [],
        voice: currentSettings.voice || 'af_heart',
        voice_formula: currentSettings.voice_formula || '',
        lang_code: currentSettings.lang_code || 'a',
        pocket_voice: currentSettings.pocket_voice || 'alba',
        nfe_step: currentSettings.nfe_step || 32,
        compile: !!currentSettings.compile,
    };
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
    // Save Settings Buttons (present in both tabs)
    document.querySelectorAll('.settings-save-btn').forEach(saveBtn => {
        saveBtn.addEventListener('click', async () => {
            const updated = getSettingsFromUI();
            try {
                saveBtn.disabled = true;
                const oldText = saveBtn.textContent;
                saveBtn.textContent = 'Saving...';
                await saveSettings(updated);
                currentSettings = updated;
                showToast('Settings saved successfully!', 'success');
                saveBtn.textContent = oldText;
            } catch (err) {
                showToast('Failed to save settings: ' + err.message, 'error');
            } finally {
                saveBtn.disabled = false;
            }
        });
    });

    // Reset Defaults Buttons (scoped to active tab)
    document.querySelectorAll('.settings-reset-btn').forEach(resetBtn => {
        resetBtn.addEventListener('click', () => {
            const scope = resetBtn.getAttribute('data-reset-scope');
            if (scope === 'normalization') {
                document.getElementById('setting-expand-numerals').checked = true;
                document.getElementById('setting-resolve-contractions').checked = true;
                document.getElementById('setting-resolve-heteronyms').checked = true;
                document.getElementById('setting-harmonize-punctuation').checked = true;
                currentSettings.custom_lexicon = [];
                renderLexiconTable([]);
                showToast('Normalization settings reset to default values.', 'info');
            } else if (scope === 'generator') {
                const defaultSynthEl = document.getElementById('default-synthesizer');
                if (defaultSynthEl) {
                    defaultSynthEl.value = getPreferredInstalledSynthesizer('dummy');
                    applyInstalledSynthesizersToSelect(defaultSynthEl);
                }
                document.getElementById('default-device').value = '';
                document.getElementById('default-speed').value = 1.0;
                document.getElementById('default-max-chars').value = 150;
                document.getElementById('default-concurrency').value = 2;
                document.getElementById('default-frame-rate').value = 24000.0;
                const fk = document.getElementById('default-fish-api-key');
                if (fk) fk.value = '';
                const fu = document.getElementById('default-fish-api-url');
                if (fu) fu.value = '';
                showToast('Generator defaults reset to default values.', 'info');
            } else {
                const defaults = {
                    expand_numerals: true,
                    resolve_contractions: true,
                    resolve_heteronyms: true,
                    harmonize_punctuation: true,
                    synthesizer: getPreferredInstalledSynthesizer('dummy'),
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
            }
        });
    });

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

    // Fish Audio Connection Test
    const testFishBtn = document.getElementById('settings-test-fish-btn');
    const fishStatusBadge = document.getElementById('settings-fish-status-badge');
    if (testFishBtn && fishStatusBadge) {
        testFishBtn.addEventListener('click', async () => {
            const apiKey = document.getElementById('default-fish-api-key')?.value.trim() || '';
            const apiUrl = document.getElementById('default-fish-api-url')?.value.trim() || '';
            fishStatusBadge.textContent = 'Testing...';
            fishStatusBadge.style.color = 'var(--text-secondary)';
            try {
                const res = await testFishConnection(apiKey, apiUrl);
                if (res.connected) {
                    fishStatusBadge.textContent = `✓ Connected (${res.type === 'cloud' ? 'Cloud' : 'Local'})`;
                    fishStatusBadge.style.color = 'var(--accent-emerald)';
                    showToast(`Fish Audio connected! ${res.message || ''}`, 'success');
                } else {
                    fishStatusBadge.textContent = '✗ Failed';
                    fishStatusBadge.style.color = 'var(--accent-rose)';
                    showToast(res.error || 'Failed to connect to Fish Audio', 'error');
                }
            } catch (err) {
                fishStatusBadge.textContent = '✗ Error';
                fishStatusBadge.style.color = 'var(--accent-rose)';
                showToast(err.message, 'error');
            }
        });
    }
}

// ── Voice Library (References Management & Recording) ─────────────────────────

let libRecordedBlob = null;
let activeAudioEl = null;

function setupVoiceLibraryHandlers() {
    const uploadBtn = document.getElementById('library-source-upload');
    const recordBtn = document.getElementById('library-source-record');
    const uploadContainer = document.getElementById('library-upload-container');
    const recorderContainer = document.getElementById('library-recorder-container');

    if (uploadBtn && recordBtn && uploadContainer && recorderContainer) {
        uploadBtn.addEventListener('click', () => {
            uploadBtn.classList.add('active-source', 'btn-primary');
            uploadBtn.classList.remove('btn-ghost');
            recordBtn.classList.remove('active-source', 'btn-primary');
            recordBtn.classList.add('btn-ghost');
            uploadContainer.style.display = 'block';
            recorderContainer.style.display = 'none';
        });

        recordBtn.addEventListener('click', () => {
            recordBtn.classList.add('active-source', 'btn-primary');
            recordBtn.classList.remove('btn-ghost');
            uploadBtn.classList.remove('active-source', 'btn-primary');
            uploadBtn.classList.add('btn-ghost');
            uploadContainer.style.display = 'none';
            recorderContainer.style.display = 'block';
        });
    }

    // Set up file upload drag-and-drop zone
    const zone = document.getElementById('library-audio-zone');
    const input = document.getElementById('library-audio-file');
    const nameDisplay = document.getElementById('library-audio-name');

    if (zone && input && nameDisplay) {
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
                nameDisplay.textContent = `📎 ${e.dataTransfer.files[0].name}`;
                nameDisplay.style.display = 'block';
            }
        });
        input.addEventListener('change', () => {
            if (input.files.length) {
                nameDisplay.textContent = `📎 ${input.files[0].name}`;
                nameDisplay.style.display = 'block';
            }
        });
    }

    // Microphone Recording events
    const libRecorderCtrl = setupAudioRecorder('#library-recorder-container', blob => {
        libRecordedBlob = blob;
    });

    // Save Reference Voice Button
    const saveVoiceBtn = document.getElementById('library-voice-save-btn');
    if (saveVoiceBtn) {
        saveVoiceBtn.addEventListener('click', async () => {
            const name = document.getElementById('library-voice-name').value.trim();
            const text = document.getElementById('library-voice-text').value.trim();

            if (!name) {
                showToast('Please enter a voice label/name.', 'error');
                return;
            }

            const body = new FormData();
            body.append('name', name);
            body.append('text', text);

            const isUpload = uploadBtn.classList.contains('active-source');
            if (isUpload) {
                const fileInput = document.getElementById('library-audio-file');
                if (!fileInput.files.length) {
                    showToast('Please select/upload an audio file first.', 'error');
                    return;
                }
                body.append('audio', fileInput.files[0]);
            } else {
                if (!libRecordedBlob) {
                    showToast('Please record some audio first.', 'error');
                    return;
                }
                body.append('audio', libRecordedBlob, `${name.replace(/\s+/g, '_')}_record.wav`);
            }

            try {
                saveVoiceBtn.disabled = true;
                saveVoiceBtn.textContent = 'Saving voice...';
                await saveReference(body);
                showToast(`Voice "${name}" saved to library!`, 'success');
                
                // Clear fields
                document.getElementById('library-voice-name').value = '';
                document.getElementById('library-voice-text').value = '';
                if (isUpload) {
                    const fileInput = document.getElementById('library-audio-file');
                    fileInput.value = '';
                    document.getElementById('library-audio-name').style.display = 'none';
                } else if (libRecorderCtrl) {
                    libRecorderCtrl.reset();
                }

                // Sync Global references dropdowns
                await loadSavedReferencesGlobal();
                await refreshVoiceLibraryList();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                saveVoiceBtn.disabled = false;
                saveVoiceBtn.textContent = '💾 Save to Voice Library';
            }
        });
    }
}

async function refreshVoiceLibraryList() {
    const grid = document.getElementById('library-voices-grid');
    if (!grid) return;
    grid.innerHTML = '<div style="text-align:center; padding: 1.5rem; color:var(--text-secondary);"><span class="spinner" style="display:inline-block; width:1rem; height:1rem; border:2px solid var(--text-secondary); border-top-color:transparent; border-radius:50%; animation:spin 1s linear infinite; margin-right:0.5rem; vertical-align:middle;"></span> Loading library...</div>';

    try {
        const refs = await fetchReferences();
        grid.innerHTML = '';
        if (refs.length === 0) {
            grid.innerHTML = '<div style="text-align:center; padding: 2rem; color:var(--text-muted); font-size:0.9rem; border:1px dashed var(--border-subtle); border-radius:var(--radius-md);">No reference voices saved. Add one using the recorder or file uploader.</div>';
            return;
        }

        refs.forEach(ref => {
            const card = document.createElement('div');
            card.className = 'voice-card';
            card.innerHTML = `
                <div class="voice-card-header">
                    <input type="text" class="voice-card-title-input" value="${escapeHtml(ref.name)}" readonly style="background:transparent; border:none; color:var(--text-primary); font-weight:600; font-size:0.95rem; width:80%; padding:0.2rem;" />
                    <div class="voice-card-actions">
                        <button type="button" class="btn btn-xs btn-ghost play-voice-btn" title="Play Voice">▶</button>
                        <button type="button" class="btn btn-xs btn-ghost edit-voice-btn" title="Edit Transcript">✏️</button>
                        <a href="/api/references/${ref.id}/audio" download class="btn btn-xs btn-ghost dl-voice-btn" title="Download Audio" style="display:flex; align-items:center;">📥</a>
                        <button type="button" class="btn btn-xs btn-ghost btn-danger delete-voice-btn" title="Delete Voice">🗑️</button>
                    </div>
                </div>
                <textarea class="voice-card-text" readonly style="width:100%; border:none; resize:none;">${escapeHtml(ref.text || 'No reference text transcript.')}</textarea>
                <audio class="voice-card-audio" src="/api/references/${ref.id}/audio" preload="none"></audio>
            `;

            const audioEl = card.querySelector('.voice-card-audio');
            const playBtn = card.querySelector('.play-voice-btn');
            const editBtn = card.querySelector('.edit-voice-btn');
            const deleteBtn = card.querySelector('.delete-voice-btn');
            const titleInput = card.querySelector('.voice-card-title-input');
            const textTextarea = card.querySelector('.voice-card-text');

            // Play / Pause Audio
            playBtn.addEventListener('click', () => {
                if (audioEl.paused) {
                    // Pause other playing reference audios
                    if (activeAudioEl && activeAudioEl !== audioEl) {
                        activeAudioEl.pause();
                        const otherCard = activeAudioEl.closest('.voice-card');
                        if (otherCard) {
                            otherCard.querySelector('.play-voice-btn').textContent = '▶';
                        }
                    }
                    audioEl.play().catch(e => showToast('Playback failed: ' + e.message, 'error'));
                    playBtn.textContent = '⏸';
                    activeAudioEl = audioEl;
                } else {
                    audioEl.pause();
                    playBtn.textContent = '▶';
                }
            });

            audioEl.onended = () => {
                playBtn.textContent = '▶';
            };

            // Edit reference
            editBtn.addEventListener('click', async () => {
                const isEditing = editBtn.classList.contains('active-edit');
                if (isEditing) {
                    // Save changes
                    const newName = titleInput.value.trim();
                    const newText = textTextarea.value.trim();
                    if (!newName) {
                        showToast('Voice name is required.', 'error');
                        return;
                    }
                    try {
                        editBtn.disabled = true;
                        await updateReference(ref.id, newName, newText);
                        showToast('Voice updated successfully!', 'success');

                        // Reset UI styling
                        titleInput.readOnly = true;
                        titleInput.style.border = '';
                        textTextarea.readOnly = true;
                        textTextarea.style.border = '';
                        textTextarea.style.background = '';
                        editBtn.classList.remove('active-edit');
                        editBtn.textContent = '✏️';
                        
                        await loadSavedReferencesGlobal();
                    } catch (e) {
                        showToast(e.message, 'error');
                    } finally {
                        editBtn.disabled = false;
                    }
                } else {
                    // Turn on edit mode
                    titleInput.readOnly = false;
                    titleInput.style.border = '1px solid var(--border-focus)';
                    titleInput.focus();
                    textTextarea.readOnly = false;
                    textTextarea.style.border = '1px solid var(--border-focus)';
                    textTextarea.style.background = 'var(--bg-primary)';

                    editBtn.classList.add('active-edit');
                    editBtn.textContent = '💾';
                }
            });

            // Delete Reference Voice
            deleteBtn.addEventListener('click', async () => {
                const currentName = titleInput.value.trim() || ref.name;
                const confirmed = await showConfirmModal(
                    "Delete Saved Voice",
                    `Are you sure you want to permanently delete reference voice "${currentName}"?`,
                    "Delete Voice",
                    "btn-danger"
                );
                if (!confirmed) return;

                try {
                    deleteBtn.disabled = true;
                    await deleteReference(ref.id);
                    showToast(`Voice "${currentName}" deleted.`, 'success');
                    await loadSavedReferencesGlobal();
                    await refreshVoiceLibraryList();
                } catch (e) {
                    showToast(e.message, 'error');
                }
            });

            grid.appendChild(card);
        });

    } catch (err) {
        grid.innerHTML = `<div style="color:var(--danger); text-align:center; padding:1.5rem;">✗ Failed to load library: ${err.message}</div>`;
    }
}
