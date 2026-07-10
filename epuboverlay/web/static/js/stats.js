import { fetchStats, fetchCacheSize } from './api.js';

export function startStatsPolling() {
    updateStats();
    setInterval(updateStats, 3000);
}

export async function updateStats() {
    try {
        const data = await fetchStats();

        // CPU
        const statCpu = document.getElementById('stat-cpu');
        const fillCpu = document.getElementById('fill-cpu');
        if (statCpu) statCpu.textContent = `${data.cpu_percent.toFixed(0)}%`;
        if (fillCpu) fillCpu.style.width = `${data.cpu_percent}%`;

        // RAM
        const statRam = document.getElementById('stat-ram');
        const fillRam = document.getElementById('fill-ram');
        if (statRam) statRam.textContent = `${data.ram_used_gb.toFixed(1)} / ${data.ram_total_gb.toFixed(0)} GB`;
        if (fillRam) fillRam.style.width = `${data.ram_percent}%`;

        // Disk
        const statDisk = document.getElementById('stat-disk');
        const fillDisk = document.getElementById('fill-disk');
        if (statDisk) statDisk.textContent = `${data.disk_used_gb.toFixed(1)} / ${data.disk_total_gb.toFixed(0)} GB`;
        if (fillDisk) fillDisk.style.width = `${data.disk_percent}%`;

        // GPU
        const gpuBadge = document.getElementById('gpu-stat-badge');
        if (gpuBadge) {
            if (data.gpu) {
                gpuBadge.style.display = 'flex';
                const gpuNameLabel = document.getElementById('gpu-name-label');
                const statGpu = document.getElementById('stat-gpu');
                const fillGpu = document.getElementById('fill-gpu');
                if (gpuNameLabel) gpuNameLabel.textContent = data.gpu.name;
                if (statGpu) statGpu.textContent = `${data.gpu.utilization.toFixed(0)}% (${data.gpu.vram_used.toFixed(1)} / ${data.gpu.vram_total.toFixed(0)} GB, ${data.gpu.temperature.toFixed(0)}°C)`;
                if (fillGpu) fillGpu.style.width = `${data.gpu.utilization}%`;
            } else {
                gpuBadge.style.display = 'none';
            }
        }

        // Cache Size
        try {
            const cacheData = await fetchCacheSize();
            const statCache = document.getElementById('stat-cache');
            if (statCache) {
                const sizeMb = (cacheData.size_bytes / (1024 * 1024)).toFixed(2);
                statCache.textContent = `${sizeMb} MB`;
            }
        } catch (cacheErr) {
            console.error('Failed to fetch cache size:', cacheErr);
        }
    } catch (err) {
        console.error('Failed to fetch resource stats:', err);
    }
}
