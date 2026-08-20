const HelpManager = {
    modal: document.getElementById('ap-modal-help'),
    btn: document.getElementById('ap-btn-help'),
    contentContainer: document.getElementById('ap-help-content'),
    isLoaded: false,

    init() {
        this.btn.addEventListener('click', () => this.open());
        this.modal.querySelector('.ap-large-modal-close').addEventListener('click', () => this.close());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.classList.contains('open')) this.close();
        });
    },

    async loadContent() {
        if (this.isLoaded) return;

        try {
            const response = await fetch('/adaptiveprompts/assets/help.html');
            if (!response.ok) throw new Error("Could not load help documentation.");

            const html = await response.text();
            this.contentContainer.innerHTML = html;
            this.isLoaded = true;
        } catch (err) {
            this.contentContainer.innerHTML = `<div style="padding: 24px; color: var(--ap-error);">Failed to load documentation: ${err.message}</div>`;
        }
    },

    open() {
        this.loadContent();
        this.modal.classList.add('open');
    },

    close() {
        this.modal.classList.remove('open');
    }
};

document.addEventListener('DOMContentLoaded', () => HelpManager.init());