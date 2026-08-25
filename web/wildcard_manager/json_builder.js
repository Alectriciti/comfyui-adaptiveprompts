// json_builder.js

const JSONBuilder = {
    mode: 'raw',
    lastJsonMode: 'builder',
    defaultEditorMode: 'last_used',
    data: { displayname: "", color: "", description: "", notes: "", variables: {}, loras: [], generate: [] },
    _expandedSetPanels: new WeakSet(),
    _draggedItem: null, // Add this to track the active drag payload
    _legacyWarningShown: false, // Tracks the one-time legacy paste warning

    init() {
        document.querySelectorAll('.ap-mode-btn').forEach(btn => {
            if (!btn) return;
            btn.onclick = () => {
                if (btn.disabled) return; // Ignore if disabled
                this.setMode(btn.dataset.mode);
                this.lastJsonMode = btn.dataset.mode;
            };
        });

        // Hook textarea scrolling and typing for the raw-mode highlighter
        const textarea = document.getElementById('ap-editor-textarea');
        const backdrop = document.getElementById('ap-raw-backdrop');

        if (textarea && backdrop) {
            textarea.addEventListener('input', (e) => {
                if (state.activeFile && state.activeFile.type === 'json') {
                    // true flag avoids full re-render on every keystroke so we don't lose focus
                    this.syncFromRaw(e.target.value, true);
                } else {
                    // .txt files use the shared Adaptive Prompts syntax highlighter
                    // instead of JSON's variable-key coloring.
                    applyTxtHighlighting(e.target.value);
                }
            });

            textarea.addEventListener('scroll', () => {
                backdrop.scrollTop = textarea.scrollTop;
                backdrop.scrollLeft = textarea.scrollLeft;
            });
        }

        // Fetched independently here (rather than reading something settings.js
        // populates) so this doesn't depend on script/init execution order.
        apiGet("/config")
            .then(data => { this.defaultEditorMode = data.default_editor_mode || 'last_used'; })
            .catch(() => { });
    },

    _bindHighlighter(inputEl, backdropEl) {
        const updateHighlight = () => {
            if (window.applyHighlights) {
                // Fetch the active file state dynamically 
                const selfRef = (typeof state !== 'undefined' && state.activeFile) ? state.activeFile.relPath : null;
                backdropEl.innerHTML = window.applyHighlights(inputEl.value, selfRef);
            } else {
                backdropEl.textContent = inputEl.value; // Fallback
            }
        };

        // Sync typing
        inputEl.addEventListener('input', updateHighlight);

        // Sync horizontal scrolling if the text gets longer than the input width
        inputEl.addEventListener('scroll', () => {
            backdropEl.scrollLeft = inputEl.scrollLeft;
        });

        // Trigger initial paint
        updateHighlight();
    },

    // The raw-mode syntax highlighter: colors a variable's key wherever it
    // appears in the raw JSON text using that variable's "label" color.
    updateRawHighlighting(text) {
        const backdrop = document.getElementById('ap-raw-backdrop');
        if (!backdrop) return;

        let highlighted = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        if (this.data && this.data.variables) {
            for (const [k, v] of Object.entries(this.data.variables)) {
                if (v.label) {
                    const regex = new RegExp(`("${k}")(\\s*:)`, 'g');
                    highlighted = highlighted.replace(regex, `<span style="color: ${v.label}; font-weight: bold; text-shadow: 0 0 6px ${v.label}40;">$1</span>$2`);
                }
            }
        }

        if (text.endsWith('\n')) highlighted += '<br/>';
        backdrop.innerHTML = highlighted;
    },

    open(jsonString) {
        const modeToggle = document.getElementById('ap-editor-mode-toggle');
        if (modeToggle) modeToggle.classList.remove('hidden');
        this.syncFromRaw(jsonString);

        const targetMode = this.defaultEditorMode === 'last_used'
            ? (this.lastJsonMode || 'builder')
            : this.defaultEditorMode;
        this.setMode(targetMode);
        this.lastJsonMode = targetMode;
    },
    close() {
        const modeToggle = document.getElementById('ap-editor-mode-toggle');
        if (modeToggle) modeToggle.classList.add('hidden');
        this.setMode('raw');
        this.updateRawHighlighting('');
    },

    setMode(mode) {
        this.mode = mode;
        const contentArea = document.getElementById('ap-editor-content-area');
        if (contentArea) contentArea.className = `ap-content-${mode}`;
        document.querySelectorAll('.ap-mode-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.mode === mode);
        });
        if (mode === 'hybrid' || mode === 'builder') this.render();
    },

    // ---------------- Sync Logic ----------------

    syncFromRaw(jsonString, skipRender = false) {
        try {
            const parsed = jsonString ? JSON.parse(jsonString) : {};
            this.normalize(parsed);
            if (this.mode !== 'raw' && !skipRender) this.render();
            this.updateRawHighlighting(jsonString); // Always update highlight
        } catch (e) {
            console.warn("[Adaptive Prompts] JSON parse error, Builder UI may not reflect latest raw changes.", e);
            this.updateRawHighlighting(jsonString); // Still update even if invalid JSON
        }
    },

    syncToRaw() {
        const cleanData = {};

        if (this.data.displayname) cleanData.displayname = this.data.displayname;
        if (this.data.color && this.data.color.toUpperCase() !== "#FFFFFF") cleanData.color = this.data.color;
        if (this.data.description) cleanData.description = this.data.description;
        if (this.data.notes) cleanData.notes = this.data.notes;

        cleanData.variables = {};
        cleanData.loras = [...this.data.loras];
        cleanData.generate = this.data.generate.map(c => this._cleanChoiceEntry(c));

        for (const [key, variable] of Object.entries(this.data.variables)) {
            cleanData.variables[key] = this._cleanVariable(variable);
        }

        const newJson = JSON.stringify(cleanData, null, 4);
        const textarea = document.getElementById('ap-editor-textarea');
        if (textarea) textarea.value = newJson;
        this.updateRawHighlighting(newJson);
    },

    // "set" is a first-class editable field now, not swept into _extra.
    _KNOWN_CHOICE_KEYS: new Set(['output', 'chance', 'weight', 'if', 'set']),

    _extractExtraKeys(choiceObj) {
        const extra = {};
        let hasExtra = false;
        for (const [k, v] of Object.entries(choiceObj)) {
            if (!this._KNOWN_CHOICE_KEYS.has(k)) { extra[k] = v; hasExtra = true; }
        }
        return hasExtra ? extra : null;
    },

    // Shared by variable choices AND generate entries -- same shape now.
    _normalizeChoiceEntry(c) {
        if (typeof c === 'object' && c !== null) {
            return {
                output: c.output || '',
                chance: c.chance ?? c.weight ?? '',
                if: c.if || '',
                set: (c.set && typeof c.set === 'object') ? { ...c.set } : null,
                _extra: this._extractExtraKeys(c),
            };
        }
        return { output: String(c), chance: '', if: '', set: null, _extra: null };
    },

    _cleanChoiceEntry(c) {
        const cleaned = { output: c.output };
        if (c.chance !== "" && c.chance !== null && !isNaN(c.chance)) cleaned.chance = Number(c.chance);
        if (c.if && c.if.trim() !== "") cleaned.if = c.if.trim();
        if (c.set && Object.keys(c.set).length > 0) cleaned.set = c.set;
        if (c._extra) Object.assign(cleaned, c._extra);
        return cleaned;
    },

    _normalizeVariableEntry(v) {
        let qty = 1;
        let choices = [];
        let label = null;
        let local = false;

        if (Array.isArray(v)) {
            choices = v;
        } else if (typeof v === 'object' && v !== null) {
            qty = v.quantity ?? 1;
            choices = v.choices || [];
            label = v.label || null;
            local = v.local || false;
        } else {
            choices = [v];
        }

        return {
            quantity: qty,
            label: label,
            local: local,
            choices: choices.map(c => this._normalizeChoiceEntry(c)),
        };
    },

    _cleanVariable(variableData) {
        const cleaned = {};
        if (variableData.label) cleaned.label = variableData.label;
        if (variableData.local) cleaned.local = true;

        cleaned.quantity = variableData.quantity || 1;
        cleaned.choices = variableData.choices.map(c => this._cleanChoiceEntry(c));
        return cleaned;
    },

    normalize(parsed) {
        this.data = { displayname: "", color: "", description: "", notes: "", variables: {}, loras: [], generate: [] };

        if (parsed.displayname) this.data.displayname = parsed.displayname;
        if (parsed.color) this.data.color = parsed.color;
        if (parsed.description) this.data.description = parsed.description;
        if (parsed.notes) this.data.notes = parsed.notes;

        if (parsed.variables) {
            for (const [k, v] of Object.entries(parsed.variables)) {
                this.data.variables[k] = this._normalizeVariableEntry(v);
            }
        }
        if (Array.isArray(parsed.loras)) this.data.loras = parsed.loras.map(String);
        if (Array.isArray(parsed.generate)) {
            this.data.generate = parsed.generate.map(g => this._normalizeChoiceEntry(g));
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

    // ---------------- Copy / Paste (variables) ----------------

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

    // ---------------- Choice Functions ----------------

    showChoiceFunctions(event, targetArray) {
        // Remove existing menu if any to prevent duplicates
        let existing = document.getElementById('ap-choice-funcs-menu');
        if (existing) existing.remove();

        const menu = document.createElement('div');
        menu.id = 'ap-choice-funcs-menu';
        menu.className = 'ap-context-menu'; // Re-use styling from context menus
        menu.style.display = 'block';

        const pasteLegacyBtn = document.createElement('button');
        pasteLegacyBtn.innerHTML = '<i class="pi pi-clipboard"></i> Paste Legacy Text';
        pasteLegacyBtn.onclick = () => {
            menu.remove();
            this.pasteLegacyText(targetArray);
        };
        menu.appendChild(pasteLegacyBtn);

        // 1. Append to body FIRST so the browser gives it physical dimensions
        document.body.appendChild(menu);

        // 2. Measure the bounds of the newly appended menu
        const menuRect = menu.getBoundingClientRect();

        let x = event.clientX;
        let y = event.clientY;

        // 3. Prevent overflow off the right side of the screen
        if (x + menuRect.width > window.innerWidth) {
            x = window.innerWidth - menuRect.width - 10; // 10px safety padding
        }

        // 4. Prevent overflow off the bottom of the screen
        if (y + menuRect.height > window.innerHeight) {
            y = window.innerHeight - menuRect.height - 10;
        }

        // Apply bounded coordinates
        menu.style.left = `${x}px`;
        menu.style.top = `${y}px`;

        // Auto-close when clicking outside
        setTimeout(() => {
            const closeMenu = (e) => {
                if (!menu.contains(e.target)) {
                    menu.remove();
                    document.removeEventListener('click', closeMenu);
                }
            };
            document.addEventListener('click', closeMenu);
        }, 0);
    },

    async pasteLegacyText(targetArray) {
        if (!this._legacyWarningShown) {
            const proceed = confirm("this will convert legacy text files and their respective weights to JSON entries, continue?");
            if (!proceed) return;
            this._legacyWarningShown = true;
        }

        let text;
        try {
            text = await navigator.clipboard.readText();
        } catch (e) {
            log(`Clipboard read failed: ${e.message}`, true);
            return;
        }

        if (!text) return;

        const lines = text.split(/\r?\n/);
        let addedCount = 0;

        for (let line of lines) {
            line = line.trim();
            if (!line) continue;
            if (line.startsWith('#')) continue;

            let output = line;
            let chance = "";

            // Matches patterns like "%2%", "%0.5%", "%2", or "%0.5" securely at the end of the line
            const weightMatch = line.match(/%([\d.]+)(?:%)?$/);
            if (weightMatch) {
                chance = Number(weightMatch[1]);
                output = line.substring(0, weightMatch.index).trim();
            }

            targetArray.push({
                output: output,
                chance: chance,
                if: '',
                set: null,
                _extra: null
            });
            addedCount++;
        }

        if (addedCount > 0) {
            log(`Parsed and converted ${addedCount} legacy entries.`);
            this.update();
        } else {
            log("No valid lines found in clipboard to parse.", true);
        }
    },

    // ---------------- Rendering & Interactions ----------------

    render() {
        const container = document.getElementById('ap-json-builder');
        container.innerHTML = '';

        // Render Metadata section first
        container.appendChild(this.createMetadataCard());

        container.appendChild(this.createSection('variables', 'Variables', () => {
            const newKey = prompt("Enter new variable name:");
            if (newKey && !this.data.variables[newKey]) {
                this.data.variables[newKey] = { quantity: 1, label: null, local: false, choices: [{ output: '', chance: '', if: '', set: null, _extra: null }] };
                this.update();
            }
        }, [
            { icon: 'pi-clipboard', title: 'Paste variable block from clipboard', onClick: () => this.pasteVariable() }
        ]));

        container.appendChild(this.createSection('loras', 'LoRAs', () => {
            this.data.loras.push("");
            this.update();
        }));

        // Choice Functions Button added securely to the left of the + Create Entry button. 
        container.appendChild(this.createSection('generate', 'Generate', () => {
            this.data.generate.push({ output: '', chance: '', if: '', set: null, _extra: null });
            this.update();
        }, [
            { icon: 'pi-file-edit', title: 'Choice Functions', onClick: (e) => this.showChoiceFunctions(e, this.data.generate) }
        ], 'bottom'));
    },

    update() {
        this.syncToRaw();
        this.render();
    },

    createSection(type, title, onAdd, extraButtons = [], addButtonPosition = 'top') {
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

        if (type === 'loras') {
            this.data.loras.forEach((val, idx) => list.appendChild(this.createSimpleRow(type, val, idx)));
        } else if (type === 'generate') {
            this.data.generate.forEach((choice, idx) => list.appendChild(this.createChoiceRow(this.data.generate, idx)));
        } else if (type === 'variables') {
            Object.entries(this.data.variables).forEach(([key, val]) => {
                list.appendChild(this.createVariableCard(key, val));
            });
        }

        wrapper.appendChild(list);

        if (addButtonPosition === 'bottom') {
            wrapper.appendChild(this.createWideAddButton('Add Entry', onAdd));
        }

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

    createWideAddButton(label, onClick) {
        const btn = document.createElement('button');
        btn.className = 'ap-wide-add-btn';
        btn.innerHTML = `<i class="pi pi-plus"></i> ${label}`;
        btn.onclick = onClick;
        return btn;
    },

    createVariableCard(key, variableData) {
        const card = document.createElement('div');
        card.className = 'ap-builder-var-card';

        // Apply coloring visually to the Builder Card
        if (variableData.label) {
            card.style.borderColor = variableData.label;
            card.style.boxShadow = `0 0 6px ${variableData.label}20`;
        }

        const header = document.createElement('div');
        header.className = 'ap-builder-var-header';

        header.innerHTML = `
            <div class="ap-var-controls">
                <input type="color" class="ap-var-color-picker" value="${variableData.label || '#3bc1ff'}" style="display:none;" />
                <button class="ap-icon-btn small ap-var-color-btn" title="Color Label">
                    <i class="pi pi-palette" ${variableData.label ? `style="color: ${variableData.label};"` : ''}></i>
                </button>

                <input type="text" class="ap-var-key" value="${key}" placeholder="Key name" title="Variable Key" ${variableData.label ? `style="color: ${variableData.label};"` : ''} />
                <label>Qty: <input type="text" class="ap-var-qty" value="${variableData.quantity}" placeholder="1 or 1-3" /></label>
                
                <label class="ap-var-local-label" title="Keep this variable strictly local">
                    <input type="checkbox" class="ap-var-local-cb" ${variableData.local ? 'checked' : ''} />
                    Local
                </label>
            </div>
            <div class="ap-var-header-actions">
                <button class="ap-icon-btn small ap-var-up" title="Move Up"><i class="pi pi-chevron-up"></i></button>
                <button class="ap-icon-btn small ap-var-down" title="Move Down"><i class="pi pi-chevron-down"></i></button>
                <button class="ap-icon-btn small ap-var-copy" title="Copy variable JSON"><i class="pi pi-copy"></i></button>
                <button class="ap-icon-btn small danger ap-var-remove" title="Remove Variable"><i class="pi pi-minus"></i></button>
            </div>
        `;

        const colorPicker = header.querySelector('.ap-var-color-picker');
        const colorBtn = header.querySelector('.ap-var-color-btn');

        colorBtn.onclick = () => colorPicker.click();
        colorPicker.oninput = (e) => {
            this.data.variables[key].label = e.target.value;
            this.update();
        };

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
        header.querySelector('.ap-var-local-cb').onchange = (e) => {
            this.data.variables[key].local = e.target.checked;
            this.syncToRaw();
        };

        const choicesHeader = document.createElement('div');
        choicesHeader.className = 'ap-builder-choices-header';

        // Structure aligns standard actions uniformly beside the add choice button
        choicesHeader.innerHTML = `
            <span>Choices</span> 
            <div class="ap-builder-section-header-actions">
                <button class="ap-icon-btn small ap-choice-funcs-btn" title="Choice Functions"><i class="pi pi-file-edit"></i></button>
                <button class="ap-icon-btn small add ap-add-choice-btn" title="Add Choice"><i class="pi pi-plus"></i></button>
            </div>
        `;

        choicesHeader.querySelector('.ap-choice-funcs-btn').onclick = (e) => this.showChoiceFunctions(e, variableData.choices);
        choicesHeader.querySelector('.ap-add-choice-btn').onclick = () => {
            this.data.variables[key].choices.push({ output: '', chance: '', if: '', set: null, _extra: null });
            this.update();
        };

        const choicesList = document.createElement('div');
        choicesList.className = 'ap-builder-choices-list';

        // --- NEW: Empty Drop Zone Fallback ---
        // If a user deletes all choices in a variable, give them a place to drop new ones
        if (variableData.choices.length === 0) {
            choicesList.style.padding = '10px';
            choicesList.style.border = '1px dashed transparent';
            choicesList.style.borderRadius = '4px';

            choicesList.addEventListener('dragover', (e) => {
                e.preventDefault();
                if (this._draggedItem) choicesList.style.borderColor = '#4ade80';
            });

            choicesList.addEventListener('dragleave', () => {
                choicesList.style.borderColor = 'transparent';
            });

            choicesList.addEventListener('drop', (e) => {
                e.preventDefault();
                if (this._draggedItem) {
                    // Splice it out of the old variable and push it into this empty one
                    const [movedItem] = this._draggedItem.array.splice(this._draggedItem.index, 1);
                    variableData.choices.push(movedItem);
                    this.update();
                }
            });
        }
        // -------------------------------------

        variableData.choices.forEach((choice, idx) => {
            choicesList.appendChild(this.createChoiceRow(variableData.choices, idx));
        });

        const addChoiceBtn = this.createWideAddButton('Add Choice', () => {
            this.data.variables[key].choices.push({ output: '', chance: '', if: '', set: null, _extra: null });
            this.update();
        });

        card.appendChild(header);
        card.appendChild(choicesHeader);
        card.appendChild(choicesList);
        card.appendChild(addChoiceBtn);
        return card;
    },

    // Shared by variable choices AND generate entries -- choicesArray is a
    // direct reference to whichever backing array (this.data.generate, or
    // this.data.variables[key].choices), so mutating it here mutates the
    // real data regardless of which section called it.
    createChoiceRow(choicesArray, index) {
        const choice = choicesArray[index];
        const hasSet = choice.set && Object.keys(choice.set).length > 0;

        const wrapper = document.createElement('div');
        wrapper.className = 'ap-choice-row-wrapper';
        wrapper.draggable = false;

        const row = document.createElement('div');
        row.className = 'ap-builder-choice-row';

        const extraBadge = choice._extra
            ? `<span class="ap-choice-extra-badge" title="Has additional unrecognized data preserved but not editable here yet"><i class="pi pi-info-circle"></i></span>`
            : '';

        const ifContainer = document.createElement('label');
        ifContainer.className = 'ap-if-container';
        ifContainer.innerHTML = `If: 
            <div class="ap-highlight-wrapper ap-choice-if-wrapper">
                <div class="ap-highlight-backdrop"></div>
                <input type="text" class="ap-choice-if" value="${choice.if.replace(/"/g, '&quot;')}" placeholder="cond == val" spellcheck="false" />
            </div>
        `;

        const ifInput = ifContainer.querySelector('.ap-choice-if');
        const ifBackdrop = ifContainer.querySelector('.ap-highlight-backdrop');
        this._bindHighlighter(ifInput, ifBackdrop);

        ifInput.oninput = (e) => { choice.if = e.target.value; this.syncToRaw(); };

        // Wrap the Output input in the highlight container with textarea support
        row.innerHTML = `
            <div class="ap-choice-drag-handle" title="Drag to reorder">
                <i class="pi pi-bars"></i>
            </div>
            <button class="ap-icon-btn small ap-choice-set-toggle ${hasSet ? 'has-set' : ''}" title="Set variables when this choice is picked">
                <i class="pi pi-chevron-right"></i>
            </button>
            <div class="ap-choice-move">
                <button class="ap-icon-btn small ap-choice-up" title="Move Up"><i class="pi pi-chevron-up"></i></button>
                <button class="ap-icon-btn small ap-choice-down" title="Move Down"><i class="pi pi-chevron-down"></i></button>
            </div>
            <div class="ap-highlight-wrapper ap-choice-out-wrapper">
                <div class="ap-highlight-backdrop"></div>
                <textarea class="ap-choice-out" placeholder="Output text..." spellcheck="false" rows="1"></textarea>
            </div>
            <label>Chance: <input type="number" step="0.25" class="ap-choice-chance" value="${choice.chance}" placeholder="1" /></label>
            ${extraBadge}
            <button class="ap-icon-btn small danger ap-choice-remove" title="Remove"><i class="pi pi-minus"></i></button>
        `;

        // Bind the output highlight with textarea support
        const outInput = row.querySelector('.ap-choice-out');
        const outBackdrop = row.querySelector('.ap-highlight-backdrop');
        outInput.value = choice.output || '';

        this._bindHighlighter(outInput, outBackdrop);

        // Handle textarea input with proper line handling
        const handleTextareaInput = (e) => {
            choice.output = e.target.value;
            this.syncToRaw();

            // Auto-resize textarea - FIXED: Use requestAnimationFrame to prevent layout thrashing
            requestAnimationFrame(() => {
                e.target.style.height = 'auto';
                // Add some padding to prevent it from being too tight
                const scrollHeight = e.target.scrollHeight;
                e.target.style.height = Math.max(scrollHeight, 30) + 'px';
            });
        };

        outInput.addEventListener('input', handleTextareaInput);

        // Handle Enter key for new lines - IMPROVED: Better cursor management
        outInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();

                // Get current cursor position
                const start = e.target.selectionStart;
                const end = e.target.selectionEnd;
                const value = e.target.value;

                // Insert newline at cursor position
                const newValue = value.substring(0, start) + '\n' + value.substring(end);
                e.target.value = newValue;

                // Move cursor to just after the newline
                setTimeout(() => {
                    e.target.selectionStart = start + 1;
                    e.target.selectionEnd = start + 1;
                    // Force re-render to make sure cursor is visible
                    handleTextareaInput(e);
                }, 0);
            }
        });

        // Ensure textarea gets proper initial sizing and focus handling
        outInput.addEventListener('focus', () => {
            // Ensure we're scrolled into view
            const wrapper = outInput.closest('.ap-choice-row-wrapper');
            if (wrapper) {
                wrapper.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        });

        // Auto-resize textarea on initial render with better timing
        requestAnimationFrame(() => {
            outInput.style.height = 'auto';
            const scrollHeight = outInput.scrollHeight;
            outInput.style.height = Math.max(scrollHeight, 30) + 'px';
        });

        // Make sure the textarea doesn't lose focus when clicking other elements
        outInput.addEventListener('mousedown', (e) => {
            // Prevent losing focus when clicking on the textarea itself
            if (e.target === outInput) {
                e.preventDefault();
                outInput.focus();
            }
        });

        row.querySelector('.ap-choice-chance').oninput = (e) => { choice.chance = e.target.value; this.syncToRaw(); };

        // Insert the ifContainer directly after the Chance label
        const chanceLabel = row.querySelector('.ap-choice-chance').parentNode;
        chanceLabel.after(ifContainer);

        // Only make the row draggable when holding down on the drag handle
        const dragHandle = row.querySelector('.ap-choice-drag-handle');
        dragHandle.addEventListener('mousedown', () => wrapper.draggable = true);
        dragHandle.addEventListener('mouseup', () => wrapper.draggable = false);
        dragHandle.addEventListener('mouseleave', () => wrapper.draggable = false);

        wrapper.addEventListener('dragstart', (e) => {
            // Store the source array and index so we know exactly what is moving
            this._draggedItem = { array: choicesArray, index: index };
            e.dataTransfer.effectAllowed = 'move';

            // A tiny timeout allows the browser to grab a snapshot of the element 
            // before we apply the opacity fade in CSS
            setTimeout(() => wrapper.classList.add('dragging'), 0);
        });

        wrapper.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necessary to allow dropping
            e.dataTransfer.dropEffect = 'move';

            // REMOVED the "draggedItem.array === choicesArray" check.
            // Now the green bar shows up no matter which variable you hover over!
            if (this._draggedItem) {
                wrapper.classList.add('drag-over');
            }
        });

        // dragleave stays exactly the same...
        wrapper.addEventListener('dragleave', (e) => {
            wrapper.classList.remove('drag-over');
        });

        wrapper.addEventListener('drop', (e) => {
            e.preventDefault();
            wrapper.classList.remove('drag-over');

            const dragged = this._draggedItem;

            // Proceed if we have a dragged item, and make sure we aren't dropping it onto itself
            // We now check if the arrays are DIFFERENT, or if the indices are DIFFERENT
            if (dragged && (dragged.array !== choicesArray || dragged.index !== index)) {

                // 1. Remove the item from its ORIGINAL array
                const [movedItem] = dragged.array.splice(dragged.index, 1);

                // 2. Calculate the target index for the NEW array
                let targetIndex = index;

                // If moving within the SAME array, and moving downwards, removing the item
                // shifted the target index up by 1. We must adjust for that.
                if (dragged.array === choicesArray && dragged.index < index) {
                    targetIndex = index - 1;
                }

                // 3. Insert the item into the target array
                choicesArray.splice(targetIndex, 0, movedItem);

                // Re-render and sync to raw JSON
                this.update();
            }
        });

        wrapper.addEventListener('dragend', () => {
            wrapper.classList.remove('dragging');
            this._draggedItem = null;
            wrapper.draggable = false;
        });

        //row.querySelector('.ap-choice-out').oninput = (e) => { choice.output = e.target.value; this.syncToRaw(); };
        //row.querySelector('.ap-choice-chance').oninput = (e) => { choice.chance = e.target.value; this.syncToRaw(); };
        row.querySelector('.ap-choice-up').onclick = () => { this.moveArrayItem(choicesArray, index, -1); this.update(); };
        row.querySelector('.ap-choice-down').onclick = () => { this.moveArrayItem(choicesArray, index, 1); this.update(); };
        row.querySelector('.ap-choice-remove').onclick = () => { choicesArray.splice(index, 1); this.update(); };

        const setPanel = this.createSetPanel(choice);
        const isExpanded = this._expandedSetPanels.has(choice);

        // If it renders already expanded, pop it into the panel
        if (isExpanded) {
            setPanel.classList.add('open');
            setPanel.insertBefore(ifContainer, setPanel.firstChild);
        }

        const toggleBtn = row.querySelector('.ap-choice-set-toggle');
        const toggleIcon = toggleBtn.querySelector('i');
        toggleIcon.className = `pi ${isExpanded ? 'pi-chevron-down' : 'pi-chevron-right'}`;

        toggleBtn.onclick = () => {
            const nowOpen = setPanel.classList.toggle('open');
            toggleIcon.className = `pi ${nowOpen ? 'pi-chevron-down' : 'pi-chevron-right'}`;
            if (nowOpen) {
                this._expandedSetPanels.add(choice);
                // Move ifContainer to the very top of the set panel
                setPanel.insertBefore(ifContainer, setPanel.firstChild);
            } else {
                this._expandedSetPanels.delete(choice);
                // Move ifContainer back to the row
                chanceLabel.after(ifContainer);
            }
        };

        wrapper.appendChild(row);
        wrapper.appendChild(setPanel);
        return wrapper;
    },

    createSetPanel(choice) {
        const panel = document.createElement('div');
        panel.className = 'ap-set-panel';

        const rebuild = () => {
            // Safely detach the ifContainer if it was moved here
            const ifContainer = panel.querySelector('.ap-if-container');
            if (ifContainer) panel.removeChild(ifContainer);

            panel.innerHTML = '';

            // Pop it right back at the top before rendering the rest
            if (ifContainer) panel.appendChild(ifContainer);

            const header = document.createElement('div');
            header.className = 'ap-set-panel-header';
            header.innerHTML = `<span><i class="pi pi-sliders-h"></i> Set on selection</span>`;
            const addBtn = document.createElement('button');
            addBtn.className = 'ap-icon-btn small add';
            addBtn.title = 'Add a variable to set';
            addBtn.innerHTML = `<i class="pi pi-plus"></i>`;
            addBtn.onclick = () => {
                if (!choice.set) choice.set = {};
                let newKey = 'flag', n = 1;
                while (choice.set[newKey] !== undefined) newKey = `flag_${n++}`;
                choice.set[newKey] = '';
                this._expandedSetPanels.add(choice);
                this.update();
            };
            header.appendChild(addBtn);
            panel.appendChild(header);

            const entries = choice.set ? Object.entries(choice.set) : [];
            if (entries.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'ap-set-empty';
                empty.textContent = 'No variables set by this choice.';
                panel.appendChild(empty);
            }

            for (const [k, v] of entries) {
                const setRow = document.createElement('div');
                setRow.className = 'ap-set-row';
                setRow.innerHTML = `
                    <input type="text" class="ap-set-key" value="${k}" placeholder="variable name" />
                    <div class="ap-highlight-wrapper ap-set-value-wrapper">
                        <div class="ap-highlight-backdrop"></div>
                        <input type="text" class="ap-set-value" value="${v.replace(/"/g, '&quot;')}" placeholder="value" spellcheck="false" />
                    </div>
                    <button class="ap-icon-btn small danger" title="Remove"><i class="pi pi-minus"></i></button>
                `;
                setRow.querySelector('.ap-set-key').onchange = (e) => {
                    const newKey = e.target.value.trim();
                    if (newKey && newKey !== k && choice.set[newKey] === undefined) {
                        const val = choice.set[k];
                        delete choice.set[k];
                        choice.set[newKey] = val;
                        this._expandedSetPanels.add(choice);
                        this.update();
                    } else {
                        e.target.value = k;
                    }
                };

                // Bind the set value highlight
                const valInput = setRow.querySelector('.ap-set-value');
                const valBackdrop = setRow.querySelector('.ap-highlight-backdrop');
                this._bindHighlighter(valInput, valBackdrop);

                valInput.oninput = (e) => {
                    choice.set[k] = e.target.value;
                    this.syncToRaw();
                };

                setRow.querySelector('button').onclick = () => {
                    delete choice.set[k];
                    if (Object.keys(choice.set).length === 0) choice.set = null;
                    this._expandedSetPanels.add(choice);
                    this.update();
                };
                panel.appendChild(setRow);
            }
        };

        rebuild();
        return panel;
    },

    createMetadataCard() {
        const card = document.createElement('div');
        card.className = 'ap-builder-meta-card';

        card.innerHTML = `
            <div class="ap-meta-row-horizontal">
                <div class="ap-meta-row" style="flex: 1;">
                    <label>Display Name</label>
                    <input type="text" class="ap-disp-input" placeholder="Overrides filename..." value="${(this.data.displayname || '').replace(/"/g, '&quot;')}" />
                </div>
                <div class="ap-meta-row" style="flex: 0.3;">
                    <label>Color</label>
                    <input type="color" class="ap-color-input" value="${this.data.color || '#ffffff'}" />
                </div>
            </div>
            <div class="ap-meta-row">
                <label>Description (Shows on card)</label>
                <input type="text" class="ap-desc-input" placeholder="A brief summary of what this wildcard does..." value="${(this.data.description || '').replace(/"/g, '&quot;')}" />
            </div>
            <div class="ap-meta-row">
                <label>Notes (Internal reference)</label>
                <!-- Added rows="2" as a baseline -->
                <textarea class="ap-notes-input" placeholder="Paste reference lists, reminders, or complex logic explanations here..." spellcheck="false" rows="2">${this.data.notes || ''}</textarea>
            </div>
        `;

        // Handle Display Name input
        card.querySelector('.ap-disp-input').oninput = (e) => {
            this.data.displayname = e.target.value;
            this.syncToRaw();
        };

        // Handle Color input
        card.querySelector('.ap-color-input').oninput = (e) => {
            this.data.color = e.target.value;
            this.syncToRaw();
        };

        // Handle Description input
        card.querySelector('.ap-desc-input').oninput = (e) => {
            this.data.description = e.target.value;
            this.syncToRaw();
        };

        // Handle Notes input with auto-resize
        const notesInput = card.querySelector('.ap-notes-input');
        const resizeNotes = () => {
            // Setting height to 0px forces scrollHeight to read purely the text contents, 
            // ignoring any massive flex-stretching it might have inherited.
            notesInput.style.height = '0px';
            notesInput.style.height = (notesInput.scrollHeight) + 'px';
        };

        notesInput.oninput = (e) => {
            this.data.notes = e.target.value;
            this.syncToRaw();
            resizeNotes();
        };

        // Delay the initial resize to ensure the DOM is fully visible and painted 
        // so scrollHeight doesn't pull a wildly incorrect layout value.
        requestAnimationFrame(() => {
            resizeNotes();
            // Secondary fallback catch for slightly slower rendering cycles
            setTimeout(resizeNotes, 50);
        });

        return card;
    },
};

document.addEventListener('DOMContentLoaded', () => JSONBuilder.init());