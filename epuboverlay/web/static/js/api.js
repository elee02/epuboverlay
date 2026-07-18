export async function fetchConfig() {
    const resp = await fetch('/api/config');
    if (!resp.ok) throw new Error('Failed to fetch config');
    return await resp.json();
}

export async function loadJobs() {
    const resp = await fetch('/api/jobs');
    if (!resp.ok) throw new Error('Failed to load jobs');
    return await resp.json();
}

export async function cancelJob(jobId) {
    const resp = await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to cancel job');
    }
    return await resp.json();
}

export async function resumeJob(jobId, formData) {
    const resp = await fetch(`/api/jobs/${jobId}/resume`, {
        method: 'POST',
        body: formData
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to resume job');
    }
    return await resp.json();
}

export async function fetchJobDetails(jobId) {
    const resp = await fetch(`/api/jobs/${jobId}`);
    if (!resp.ok) throw new Error('Failed to fetch job details');
    return await resp.json();
}

export async function deleteJob(jobId) {
    const resp = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to delete job');
    }
    return await resp.json();
}

export async function purgeAllCache() {
    const resp = await fetch('/api/cache', { method: 'DELETE' });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to purge cache');
    }
    return await resp.json();
}

export async function fetchCacheSize() {
    const resp = await fetch('/api/cache/size');
    if (!resp.ok) throw new Error('Failed to fetch cache size');
    return await resp.json();
}

export async function fetchStats() {
    const resp = await fetch('/api/stats');
    if (!resp.ok) throw new Error('Failed to fetch stats');
    return await resp.json();
}

export async function previewVoice(formData) {
    const resp = await fetch('/api/preview', {
        method: 'POST',
        body: formData
    });
    if (!resp.ok) {
        let detail = 'Failed to generate voice preview';
        try { const err = await resp.json(); detail = err.detail || detail; } catch (_) {}
        throw new Error(detail);
    }
    return await resp.blob();
}

export async function fetchChapters(file) {
    const formData = new FormData();
    formData.append('epub', file);
    const resp = await fetch('/api/chapters', {
        method: 'POST',
        body: formData
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to extract chapters');
    }
    return await resp.json();
}

export async function fetchSettings() {
    const resp = await fetch('/api/settings');
    if (!resp.ok) throw new Error('Failed to fetch settings');
    return await resp.json();
}

export async function saveSettings(settings) {
    const resp = await fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(settings)
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to save settings');
    }
    return await resp.json();
}

export async function fetchReferences() {
    const resp = await fetch('/api/references');
    if (!resp.ok) throw new Error('Failed to fetch references');
    return await resp.json();
}

export async function saveReference(formData) {
    const resp = await fetch('/api/references', {
        method: 'POST',
        body: formData
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to save reference voice');
    }
    return await resp.json();
}

export async function updateReference(refId, name, text) {
    const formData = new FormData();
    formData.append('name', name);
    formData.append('text', text);
    const resp = await fetch(`/api/references/${encodeURIComponent(refId)}`, {
        method: 'PUT',
        body: formData
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to update reference voice');
    }
    return await resp.json();
}

export async function deleteReference(refId) {
    const resp = await fetch(`/api/references/${encodeURIComponent(refId)}`, {
        method: 'DELETE'
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to delete reference voice');
    }
    return await resp.json();
}

export async function fetchPlaygroundHistory() {
    const resp = await fetch('/api/playground/history');
    if (!resp.ok) throw new Error('Failed to fetch playground history');
    return await resp.json();
}

export async function clearPlaygroundCache() {
    const resp = await fetch('/api/playground/cache', {
        method: 'DELETE'
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to clear playground cache');
    }
    return await resp.json();
}


export async function convertJobToAudio(jobId, merge, formats, center, mp4Video, embedSubtitles, includeAudio, coverArtFile, audioFormat) {
    const formData = new FormData();
    formData.append('merge', merge ? 'true' : 'false');
    formData.append('formats', (formats && formats.length > 0) ? formats.join(',') : 'none');
    formData.append('center', center ? 'true' : 'false');
    formData.append('mp4_video', mp4Video ? 'true' : 'false');
    formData.append('embed_subtitles', embedSubtitles ? 'true' : 'false');
    formData.append('include_audio', includeAudio ? 'true' : 'false');
    formData.append('audio_format', audioFormat || 'm4b');
    if (coverArtFile) {
        formData.append('cover_art', coverArtFile);
    }
    const resp = await fetch(`/api/jobs/${jobId}/convert-audio`, {
        method: 'POST',
        body: formData
    });
    if (!resp.ok) {
        let detail = 'Failed to convert to audio';
        try {
            const err = await resp.json();
            detail = err.detail || detail;
        } catch (_) {}
        throw new Error(detail);
    }
    return resp.blob();
}

export async function fetchVoiceBlends() {
    const resp = await fetch('/api/voice-blends');
    if (!resp.ok) throw new Error('Failed to fetch voice blends');
    return await resp.json();
}

export async function saveVoiceBlend(blend) {
    const resp = await fetch('/api/voice-blends', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(blend)
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to save voice blend');
    }
    return await resp.json();
}

export async function deleteVoiceBlend(name) {
    const resp = await fetch(`/api/voice-blends/${encodeURIComponent(name)}`, {
        method: 'DELETE'
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to delete voice blend');
    }
    return await resp.json();
}

