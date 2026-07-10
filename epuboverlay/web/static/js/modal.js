export function showConfirmModal(title, message, confirmText = 'Confirm', confirmClass = 'btn-primary') {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <h3>${title}</h3>
                    <button class="modal-close-btn">&times;</button>
                </div>
                <div style="margin-bottom: 1.5rem; font-size: 0.95rem; line-height: 1.5; color: var(--text-secondary);">
                    ${message}
                </div>
                <div style="display: flex; justify-content: flex-end; gap: 0.75rem;">
                    <button class="btn btn-ghost modal-cancel-btn">Cancel</button>
                    <button class="btn ${confirmClass} modal-confirm-btn">${confirmText}</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        
        // Force reflow and activate transition
        overlay.offsetHeight;
        overlay.classList.add('active');

        const cleanUp = () => {
            overlay.classList.remove('active');
            setTimeout(() => {
                overlay.remove();
            }, 300);
        };

        overlay.querySelector('.modal-close-btn').addEventListener('click', () => {
            cleanUp();
            resolve(false);
        });

        overlay.querySelector('.modal-cancel-btn').addEventListener('click', () => {
            cleanUp();
            resolve(false);
        });

        overlay.querySelector('.modal-confirm-btn').addEventListener('click', () => {
            cleanUp();
            resolve(true);
        });

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                cleanUp();
                resolve(false);
            }
        });
    });
}
