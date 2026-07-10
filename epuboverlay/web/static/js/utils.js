export const toastContainer = document.getElementById('toast-container');

export function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { success: '✓', error: '✗', info: 'ℹ' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span> <span>${message}</span>`;
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

export function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
