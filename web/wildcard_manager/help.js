const HelpManager = {
    modal: document.getElementById('ap-modal-help'),
    btn: document.getElementById('ap-btn-help'),

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

    open() { this.modal.classList.add('open'); },
    close() { this.modal.classList.remove('open'); }
};

document.addEventListener('DOMContentLoaded', () => HelpManager.init());