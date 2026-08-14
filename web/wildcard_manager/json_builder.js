// json_builder.js

const JSONBuilder = {
    mode: 'raw', // 'raw', 'builder', 'hybrid'
    data: { variables: {}, loras: [], generate: [] },

    init() {
        // Bind mode toggles
        document.querySelectorAll('.ap-mode-btn').forEach(btn => {
            btn.onclick = (e) => {
                document.querySelectorAll('.ap-mode-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.setMode(btn.dataset.mode);
            };
        });
    },

    open(jsonString) {
        document.getElementById('ap-editor-mode-toggle').classList.remove('hidden');
        this.syncFromRaw(jsonString);

        // Default to builder mode if opening a JSON file
        const defaultMode = 'builder';
        document.querySelector(`.ap-mode-btn[data-mode="${defaultMode}"]`).click();
    },

    close() {
        document.getElementById('ap-editor-mode-toggle').classList.add('hidden');
        this.setMode('raw');
    },

    setMode(mode) {
        this.mode = mode;
        const container = document.getElementById('ap-editor-content-area');
        container.className = `ap-content-${mode}`;

        if (mode === 'hybrid' || mode === 'builder') {
            this.render();
        }
    },

    // ---------------- Sync Logic ----------------

    syncFromRaw(jsonString) {
        try {
            const parsed = jsonString ? JSON.parse(jsonString) : {};
            this.normalize(parsed);
            if (this.mode !== 'raw') this.render();
        } catch (e) {
            console.warn("[Adaptive Prompts] JSON parse error, Builder UI may not reflect latest raw changes.", e);
        }
    },

    syncToRaw() {
        const cleanData = { variables: {}, loras: [...this.data.loras], generate: [...this.data.generate] };

        // Strip out empty optional parameters as requested
        for (const [key, variable] of Object.entries(this.data.variables)) {
            cleanData.variables[key] = {
                quantity: variable.quantity || 1,
                choices: variable.choices.map(c => {
                    const cleaned = { output: c.output };
                    if (c.chance !== "" && c.chance !== null && !isNaN(c.chance)) cleaned.chance = Number(c.chance);
                    if (c.if && c.if.trim() !== "") cleaned.if = c.if.trim();
                    return cleaned;
                })
            };
        }

        const ta = document.getElementById('ap-editor-textarea');
        ta.value = JSON.stringify(cleanData, null, 4);
    },

    normalize(parsed) {
        this.data = { variables: {}, loras: [], generate: [] };

        if (parsed.variables) {
            for (const [k, v] of Object.entries(parsed.variables)) {
                let qty = 1;
                let choices = [];

                if (Array.isArray(v)) {
                    choices = v;
                } else if (typeof v === 'object' && v !== null) {
                    qty = v.quantity ?? 1;
                    choices = v.choices || [];
                } else {
                    choices = [v];
                }

                this.data.variables[k] = {
                    quantity: qty,
                    choices: choices.map(c => {
                        if (typeof c === 'object' && c !== null) {
                            return { output: c.output || '', chance: c.chance || c.weight || '', if: c.if || '' };
                        }
                        return { output: String(c), chance: '', if: '' };
                    })
                };
            }
        }

        if (Array.isArray(parsed.loras)) this.data.loras = parsed.loras.map(String);
        if (Array.isArray(parsed.generate)) {
            this.data.generate = parsed.generate.map(g => typeof g === 'object' ? g.output : String(g));
        }
    },

    // ---------------- Rendering & Interactions ----------------

    render() {
        const container = document.getElementById('ap-json-builder');
        container.innerHTML = '';

        container.appendChild(this.createSection('variables', 'Variables', () => {
            const newKey = prompt("Enter new variable name:");
            if (newKey && !this.data.variables[newKey]) {
                this.data.variables[newKey] = { quantity: 1, choices: [{ output: '', chance: '', if: '' }] };
                this.update();
            }
        }));

        container.appendChild(this.createSection('loras', 'LoRAs', () => {
            this.data.loras.push("");
            this.update();
        }));

        container.appendChild(this.createSection('generate', 'Generate', () => {
            this.data.generate.push("");
            this.update();
        }));
    },

    update() {
        this.syncToRaw();
        this.render();
    },

    createSection(type, title, onAdd) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ap-builder-section';

        const header = document.createElement('div');
        header.className = 'ap-builder-section-header';
        header.innerHTML = `<span>${title}</span> <button class="ap-icon-btn small" title="Add Entry"><i class="pi pi-plus"></i></button>`;
        header.querySelector('button').onclick = onAdd;
        wrapper.appendChild(header);

        const list = document.createElement('div');
        list.className = 'ap-builder-list';

        if (type === 'loras') {
            this.data.loras.forEach((val, idx) => list.appendChild(this.createSimpleRow(type, val, idx)));
        } else if (type === 'generate') {
            this.data.generate.forEach((val, idx) => list.appendChild(this.createSimpleRow(type, val, idx)));
        } else if (type === 'variables') {
            Object.entries(this.data.variables).forEach(([key, val]) => {
                list.appendChild(this.createVariableCard(key, val));
            });
        }

        wrapper.appendChild(list);
        return wrapper;
    },

    createSimpleRow(type, value, index) {
        const row = document.createElement('div');
        row.className = 'ap-builder-row';
        row.innerHTML = `
            <input type="text" value="${value}" placeholder="Enter ${type.slice(0, -1)} string..." />
            <button class="ap-icon-btn small danger" title="Remove"><i class="pi pi-minus"></i></button>
        `;

        const input = row.querySelector('input');
        input.oninput = (e) => {
            this.data[type][index] = e.target.value;
            this.syncToRaw(); // Immediate sync
        };

        row.querySelector('button').onclick = () => {
            this.data[type].splice(index, 1);
            this.update();
        };

        return row;
    },

    createVariableCard(key, variableData) {
        const card = document.createElement('div');
        card.className = 'ap-builder-var-card';

        const header = document.createElement('div');
        header.className = 'ap-builder-var-header';
        header.innerHTML = `
            <div class="ap-var-controls">
                <input type="text" class="ap-var-key" value="${key}" placeholder="Key name" title="Variable Key"/>
                <label>Qty: <input type="text" class="ap-var-qty" value="${variableData.quantity}" placeholder="1 or 1-3" /></label>
            </div>
            <button class="ap-icon-btn small danger ap-var-remove" title="Remove Variable"><i class="pi pi-minus"></i></button>
        `;

        // Key rename logic
        const keyInput = header.querySelector('.ap-var-key');
        keyInput.onchange = (e) => {
            const newKey = e.target.value.trim();
            if (newKey && newKey !== key && !this.data.variables[newKey]) {
                this.data.variables[newKey] = this.data.variables[key];
                delete this.data.variables[key];
                this.update();
            } else {
                e.target.value = key; // Revert if empty or duplicate
            }
        };

        // Quantity logic
        header.querySelector('.ap-var-qty').oninput = (e) => {
            this.data.variables[key].quantity = e.target.value;
            this.syncToRaw();
        };

        header.querySelector('.ap-var-remove').onclick = () => {
            if (confirm(`Remove variable '${key}'?`)) {
                delete this.data.variables[key];
                this.update();
            }
        };

        const choicesHeader = document.createElement('div');
        choicesHeader.className = 'ap-builder-choices-header';
        choicesHeader.innerHTML = `<span>Choices</span> <button class="ap-icon-btn small" title="Add Choice"><i class="pi pi-plus"></i></button>`;
        choicesHeader.querySelector('button').onclick = () => {
            this.data.variables[key].choices.push({ output: '', chance: '', if: '' });
            this.update();
        };

        const choicesList = document.createElement('div');
        choicesList.className = 'ap-builder-choices-list';
        variableData.choices.forEach((choice, idx) => {
            choicesList.appendChild(this.createChoiceRow(key, choice, idx));
        });

        card.appendChild(header);
        card.appendChild(choicesHeader);
        card.appendChild(choicesList);
        return card;
    },

    createChoiceRow(varKey, choice, index) {
        const row = document.createElement('div');
        row.className = 'ap-builder-choice-row';
        row.innerHTML = `
            <input type="text" class="ap-choice-out" value="${choice.output}" placeholder="Output text..." />
            <label>Chance: <input type="number" class="ap-choice-chance" value="${choice.chance}" placeholder="1" /></label>
            <label>If: <input type="text" class="ap-choice-if" value="${choice.if}" placeholder="cond == val" /></label>
            <button class="ap-icon-btn small danger" title="Remove Choice"><i class="pi pi-minus"></i></button>
        `;

        // Bind all inputs for immediate raw syncing
        row.querySelector('.ap-choice-out').oninput = (e) => { this.data.variables[varKey].choices[index].output = e.target.value; this.syncToRaw(); };
        row.querySelector('.ap-choice-chance').oninput = (e) => { this.data.variables[varKey].choices[index].chance = e.target.value; this.syncToRaw(); };
        row.querySelector('.ap-choice-if').oninput = (e) => { this.data.variables[varKey].choices[index].if = e.target.value; this.syncToRaw(); };

        row.querySelector('button').onclick = () => {
            this.data.variables[varKey].choices.splice(index, 1);
            this.update();
        };

        return row;
    }
};

// Initialize once script loads
document.addEventListener('DOMContentLoaded', () => JSONBuilder.init());