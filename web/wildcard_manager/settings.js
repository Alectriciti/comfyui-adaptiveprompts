const SettingsManager = {
    modal: document.getElementById('ap-modal-settings'),
    btn: document.getElementById('ap-btn-settings'),
    aspectSelect: document.getElementById('ap-setting-aspect'),
    defaultModeSelect: document.getElementById('ap-setting-default-mode'),
    grid: document.getElementById('ap-file-grid'),
    config: {}, // Local cache to prevent overwriting keys on save

    async init() {
        try {
            this.config = await apiGet("/config");
            const aspect = this.config.card_aspect || 'portrait';
            this.applyAspect(aspect);
            this.aspectSelect.value = aspect;
            this.defaultModeSelect.value = this.config.default_editor_mode || 'last_used';
        } catch (e) {
            console.error("Failed to load settings:", e);
            this.applyAspect('portrait');
        }

        this.btn.addEventListener('click', () => this.open());
        this.modal.querySelector('.ap-large-modal-close').addEventListener('click', () => this.close());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('open')) this.close();
        });

        this.aspectSelect.addEventListener('change', async (e) => {
            const val = e.target.value;
            this.applyAspect(val);
            try {
                this.config.card_aspect = val;
                await apiSend("/config", this.config); // Send the complete object
            } catch (err) {
                log(`Failed to save settings: ${err.message}`, true);
            }
        });

        this.defaultModeSelect.addEventListener('change', async (e) => {
            const val = e.target.value;
            try {
                this.config.default_editor_mode = val;
                await apiSend("/config", this.config); // Send the complete object

                if (typeof JSONBuilder !== 'undefined') JSONBuilder.defaultEditorMode = val;
                log(`Default editor mode set to "${val}"`);
            } catch (err) {
                log(`Failed to save settings: ${err.message}`, true);
            }
        });
    },

    applyAspect(val) {
        this.grid.classList.remove('aspect-portrait', 'aspect-square', 'aspect-landscape');
        this.grid.classList.add(`aspect-${val}`);
    },

    open() { this.modal.classList.add('open'); },
    close() { this.modal.classList.remove('open'); }
};

document.addEventListener('DOMContentLoaded', () => SettingsManager.init());