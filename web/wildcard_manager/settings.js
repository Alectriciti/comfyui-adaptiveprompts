const SettingsManager = {
    modal: document.getElementById('ap-modal-settings'),
    btn: document.getElementById('ap-btn-settings'),
    aspectSelect: document.getElementById('ap-setting-aspect'),
    grid: document.getElementById('ap-file-grid'),

    async init() {
        // Fetch Initial Config
        try {
            const data = await apiGet("/config");
            const aspect = data.card_aspect || 'portrait';
            this.applyAspect(aspect);
            this.aspectSelect.value = aspect;
        } catch (e) {
            console.error("Failed to load settings:", e);
            this.applyAspect('portrait'); // Fallback
        }

        // Bind UI Events
        this.btn.addEventListener('click', () => this.open());
        this.modal.querySelector('.ap-large-modal-close').addEventListener('click', () => this.close());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('open')) this.close();
        });

        // Handle Change Event
        this.aspectSelect.addEventListener('change', async (e) => {
            const val = e.target.value;
            this.applyAspect(val);
            try {
                await apiSend("/config", { card_aspect: val });
            } catch (err) {
                log(`Failed to save settings: ${err.message}`, true);
            }
        });
    },

    applyAspect(val) {
        // Clear all previous aspect classes and apply new one
        this.grid.classList.remove('aspect-portrait', 'aspect-square', 'aspect-landscape');
        this.grid.classList.add(`aspect-${val}`);
    },

    open() { this.modal.classList.add('open'); },
    close() { this.modal.classList.remove('open'); }
};

document.addEventListener('DOMContentLoaded', () => SettingsManager.init());