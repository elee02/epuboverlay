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

export async function saveProfile(name, settings) {
    const resp = await fetch('/api/profiles', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name, settings })
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to save profile');
    }
    return await resp.json();
}

export async function deleteProfile(name) {
    const resp = await fetch(`/api/profiles/${encodeURIComponent(name)}`, {
        method: 'DELETE'
    });
    if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to delete profile');
    }
    return await resp.json();
}

export async function convertJobToAudio(jobId, merge, formats, center, mp4Video, embedSubtitles, includeAudio, coverArtFile) {
    const formData = new FormData();
    formData.append('merge', merge ? 'true' : 'false');
    if (formats && formats.length > 0) {
        formData.append('formats', formats.join(','));
    }
    formData.append('center', center ? 'true' : 'false');
    formData.append('mp4_video', mp4Video ? 'true' : 'false');
    formData.append('embed_subtitles', embedSubtitles ? 'true' : 'false');
    formData.append('include_audio', includeAudio ? 'true' : 'false');
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
