// json_builder.js

const JSONBuilder = {
    mode: 'raw', // 'raw', 'builder', 'hybrid'
    data: { variables: {}, loras: [], generate: [] },

    init() {
        document.querySelectorAll('.ap-mode-btn').forEach(btn => {
            btn.onclick = () => this.setMode(btn.dataset.mode);
        });
    },

    open(jsonString) {
        document.getElementById('ap-editor-mode-toggle').classList.remove('hidden');
        this.syncFromRaw(jsonString);
        // Re-render in whatever mode was already active instead of forcing
        // 'builder' every time -- only close() (txt files) forces back to raw.
        this.setMode(this.mode);
    },

    close() {
        document.getElementById('ap-editor-mode-toggle').classList.add('hidden');
        this.setMode('raw');
    },

    setMode(mode) {
        this.mode = mode;
        document.getElementById('ap-editor-content-area').className = `ap-content-${mode}`;
        document.querySelectorAll('.ap-mode-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.mode === mode);
        });
        if (mode === 'hybrid' || mode === 'builder') this.render();
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
        for (const [key, variable] of Object.entries(this.data.variables)) {
            cleanData.variables[key] = this._cleanVariable(variable);
        }
        document.getElementById('ap-editor-textarea').value = JSON.stringify(cleanData, null, 4);
    },

    // Known/editable choice keys. Anything else (eg "set", a side-effect command
    // the backend supports but this UI doesn't have a widget for yet) gets
    // carried through untouched so it's never silently dropped by the Builder
    // or by copy/paste -- see _extractExtraKeys / _cleanVariable below.
    _KNOWN_CHOICE_KEYS: new Set(['output', 'chance', 'weight', 'if']),

    _extractExtraKeys(choiceObj) {
        const extra = {};
        let hasExtra = false;
        for (const [k, v] of Object.entries(choiceObj)) {
            if (!this._KNOWN_CHOICE_KEYS.has(k)) { extra[k] = v; hasExtra = true; }
        }
        return hasExtra ? extra : null;
    },

    _normalizeVariableEntry(v) {
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

        return {
            quantity: qty,
            choices: choices.map(c => {
                if (typeof c === 'object' && c !== null) {
                    return {
                        output: c.output || '',
                        chance: c.chance ?? c.weight ?? '',
                        if: c.if || '',
                        _extra: this._extractExtraKeys(c),
                    };
                }
                return { output: String(c), chance: '', if: '', _extra: null };
            })
        };
    },

    _cleanVariable(variableData) {
        return {
            quantity: variableData.quantity || 1,
            choices: variableData.choices.map(c => {
                const cleaned = { output: c.output };
                if (c.chance !== "" && c.chance !== null && !isNaN(c.chance)) cleaned.chance = Number(c.chance);
                if (c.if && c.if.trim() !== "") cleaned.if = c.if.trim();
                if (c._extra) Object.assign(cleaned, c._extra); // eg "set" -- preserved, not editable here yet
                return cleaned;
            })
        };
    },

    normalize(parsed) {
        this.data = { variables: {}, loras: [], generate: [] };
        if (parsed.variables) {
            for (const [k, v] of Object.entries(parsed.variables)) {
                this.data.variables[k] = this._normalizeVariableEntry(v);
            }
        }
        if (Array.isArray(parsed.loras)) this.data.loras = parsed.loras.map(String);
        if (Array.isArray(parsed.generate)) {
            this.data.generate = parsed.generate.map(g => typeof g === 'object' ? g.output : String(g));
        }
    },

    // ---------------- Reordering ----------------

    moveArrayItem(arr, index, direction) {
        const target = index + direction;
        if (target < 0 || target >= arr.length) return;
        [arr[index], arr[target]] = [arr[target], arr[index]];
    },

    moveVariableKey(key, direction) {
        const keys = Object.keys(this.data.variables);
        const index = keys.indexOf(key);
        const target = index + direction;
        if (target < 0 || target >= keys.length) return;
        [keys[index], keys[target]] = [keys[target], keys[index]];
        const reordered = {};
        for (const k of keys) reordered[k] = this.data.variables[k];
        this.data.variables = reordered;
        this.update();
    },

    // ---------------- Copy / Paste ----------------

    async copyVariable(key) {
        const payload = { [key]: this._cleanVariable(this.data.variables[key]) };
        try {
            await navigator.clipboard.writeText(JSON.stringify(payload, null, 4));
            log(`Copied variable "${key}" to clipboard`);
        } catch (e) {
            log(`Copy failed: ${e.message}`, true);
        }
    },

    async pasteVariable() {
        let text;
        try {
            text = await navigator.clipboard.readText();
        } catch (e) {
            log(`Clipboard read failed: ${e.message}`, true);
            return;
        }

        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (e) {
            log("Clipboard doesn't contain valid JSON to paste as a variable.", true);
            return;
        }

        const entries = Object.entries(parsed || {});
        if (entries.length === 0) {
            log("Clipboard JSON has no variable entries to paste.", true);
            return;
        }

        for (let [key, value] of entries) {
            if (this.data.variables[key]) {
                const newKey = prompt(`"${key}" already exists here. Enter a new name (or cancel to skip):`, `${key}_copy`);
                if (!newKey) continue;
                key = newKey;
            }
            this.data.variables[key] = this._normalizeVariableEntry(value);
        }
        log("Pasted variable block from clipboard.");
        this.update();
    },

    // ---------------- Rendering & Interactions ----------------

    render() {
        const container = document.getElementById('ap-json-builder');
        container.innerHTML = '';

        container.appendChild(this.createSection('variables', 'Variables', () => {
            const newKey = prompt("Enter new variable name:");
            if (newKey && !this.data.variables[newKey]) {
                this.data.variables[newKey] = { quantity: 1, choices: [{ output: '', chance: '', if: '', _extra: null }] };
                this.update();
            }
        }, [
            { icon: 'pi-clipboard', title: 'Paste variable block from clipboard', onClick: () => this.pasteVariable() }
        ]));

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

    createSection(type, title, onAdd, extraButtons = []) {
        const wrapper = document.createElement('div');
        wrapper.className = 'ap-builder-section';

        const header = document.createElement('div');
        header.className = 'ap-builder-section-header';
        header.innerHTML = `<span>${title}</span>`;

        const btnGroup = document.createElement('div');
        btnGroup.className = 'ap-builder-section-header-actions';

        for (const extra of extraButtons) {
            const btn = document.createElement('button');
            btn.className = 'ap-icon-btn small';
            btn.title = extra.title;
            btn.innerHTML = `<i class="pi ${extra.icon}"></i>`;
            btn.onclick = extra.onClick;
            btnGroup.appendChild(btn);
        }

        const addBtn = document.createElement('button');
        addBtn.className = 'ap-icon-btn small add';
        addBtn.title = 'Add Entry';
        addBtn.innerHTML = `<i class="pi pi-plus"></i>`;
        addBtn.onclick = onAdd;
        btnGroup.appendChild(addBtn);

        header.appendChild(btnGroup);
        wrapper.appendChild(header);

        const list = document.createElement('div');
        list.className = 'ap-builder-list';

        if (type === 'loras' || type === 'generate') {
            this.data[type].forEach((val, idx) => list.appendChild(this.createSimpleRow(type, val, idx)));
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

        row.querySelector('input').oninput = (e) => {
            this.data[type][index] = e.target.value;
            this.syncToRaw();
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
            <div class="ap-var-header-actions">
                <button class="ap-icon-btn small ap-var-up" title="Move Up"><i class="pi pi-chevron-up"></i></button>
                <button class="ap-icon-btn small ap-var-down" title="Move Down"><i class="pi pi-chevron-down"></i></button>
                <button class="ap-icon-btn small ap-var-copy" title="Copy variable JSON"><i class="pi pi-copy"></i></button>
                <button class="ap-icon-btn small danger ap-var-remove" title="Remove Variable"><i class="pi pi-minus"></i></button>
            </div>
        `;

        const keyInput = header.querySelector('.ap-var-key');
        keyInput.onchange = (e) => {
            const newKey = e.target.value.trim();
            if (newKey && newKey !== key && !this.data.variables[newKey]) {
                this.data.variables[newKey] = this.data.variables[key];
                delete this.data.variables[key];
                this.update();
            } else {
                e.target.value = key;
            }
        };

        header.querySelector('.ap-var-qty').oninput = (e) => {
            this.data.variables[key].quantity = e.target.value;
            this.syncToRaw();
        };

        header.querySelector('.ap-var-up').onclick = () => this.moveVariableKey(key, -1);
        header.querySelector('.ap-var-down').onclick = () => this.moveVariableKey(key, 1);
        header.querySelector('.ap-var-copy').onclick = () => this.copyVariable(key);
        header.querySelector('.ap-var-remove').onclick = () => {
            if (confirm(`Remove variable '${key}'?`)) {
                delete this.data.variables[key];
                this.update();
            }
        };

        const choicesHeader = document.createElement('div');
        choicesHeader.className = 'ap-builder-choices-header';
        choicesHeader.innerHTML = `<span>Choices</span> <button class="ap-icon-btn small add" title="Add Choice"><i class="pi pi-plus"></i></button>`;
        choicesHeader.querySelector('button').onclick = () => {
            this.data.variables[key].choices.push({ output: '', chance: '', if: '', _extra: null });
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
        const extraBadge = choice._extra
            ? `<span class="ap-choice-extra-badge" title="Has additional data (eg 'set') preserved but not editable here yet"><i class="pi pi-info-circle"></i></span>`
            : '';
        row.innerHTML = `
            <div class="ap-choice-move">
                <button class="ap-icon-btn small ap-choice-up" title="Move Up"><i class="pi pi-chevron-up"></i></button>
                <button class="ap-icon-btn small ap-choice-down" title="Move Down"><i class="pi pi-chevron-down"></i></button>
            </div>
            <input type="text" class="ap-choice-out" value="${choice.output}" placeholder="Output text..." />
            <label>Chance: <input type="number" step="0.25" class="ap-choice-chance" value="${choice.chance}" placeholder="1" /></label>
            <label>If: <input type="text" class="ap-choice-if" value="${choice.if}" placeholder="cond == val" /></label>
            ${extraBadge}
            <button class="ap-icon-btn small danger" title="Remove Choice"><i class="pi pi-minus"></i></button>
        `;

        const choices = this.data.variables[varKey].choices;
        row.querySelector('.ap-choice-out').oninput = (e) => { choices[index].output = e.target.value; this.syncToRaw(); };
        row.querySelector('.ap-choice-chance').oninput = (e) => { choices[index].chance = e.target.value; this.syncToRaw(); };
        row.querySelector('.ap-choice-if').oninput = (e) => { choices[index].if = e.target.value; this.syncToRaw(); };
        row.querySelector('.ap-choice-up').onclick = () => { this.moveArrayItem(choices, index, -1); this.update(); };
        row.querySelector('.ap-choice-down').onclick = () => { this.moveArrayItem(choices, index, 1); this.update(); };
        row.querySelector('.ap-choice-row-remove, button[title="Remove Choice"]').onclick = () => {
            choices.splice(index, 1);
            this.update();
        };

        return row;
    }
};

document.addEventListener('DOMContentLoaded', () => JSONBuilder.init());