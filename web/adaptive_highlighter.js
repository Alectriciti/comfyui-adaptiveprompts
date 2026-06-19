import { app } from "../../scripts/app.js";

// --- 1. CONFIGURABLE COLORS ---
const style = document.createElement("style");
style.innerHTML = `
    :root {
        --ap-bracket: #4ade80; 
        --ap-wildcard: #3bc1ff;
        --ap-wildcard-var: #49ffe1;    /* Distinct color for ^variable */
        --ap-lora-base: #5f5db4;
        --ap-lora-name: #9b95ee;
        --ap-lora-x: #ac58ff;
        --ap-lora-y: #f0dc79;
        --ap-lora-z: #4ade80;
        --ap-error: #f87171;
        
        --ap-editor-bg: #1e1e1e;
        --ap-editor-text: #cccccc;
    }

    .ap-editor-container {
        position: relative;
        width: 100%;
        height: 100%;
        font-family: monospace;
        font-size: 14px;
        line-height: 1.4;
    }

    .ap-editor-backdrop {
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        overflow: hidden;
        white-space: pre-wrap;
        word-wrap: break-word;
        color: var(--ap-editor-text);
        background: var(--ap-editor-bg);
        pointer-events: none;
        padding: 6px;
        box-sizing: border-box;
        border-radius: 4px;
    }

    .ap-editor-textarea {
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        width: 100%; height: 100%;
        background: transparent !important;
        color: transparent !important;
        caret-color: white;
        resize: none;
        border: 1px solid #333;
        outline: none;
        padding: 6px;
        box-sizing: border-box;
        font-family: inherit;
        font-size: inherit;
        line-height: inherit;
        border-radius: 4px;
    }

    .ap-bracket { color: var(--ap-bracket); font-weight: bold; }
    .ap-wildcard { color: var(--ap-wildcard); }
    .ap-wildcard-var { color: var(--ap-wildcard-var); }
    .ap-lora { color: var(--ap-lora-base); }
    .ap-lora-name { color: var(--ap-lora-name); }
    .ap-lora-x { color: var(--ap-lora-x); }
    .ap-lora-y { color: var(--ap-lora-y); }
    .ap-lora-z { color: var(--ap-lora-z); }
    .ap-error { 
        color: var(--ap-error); 
        text-decoration: underline wavy var(--ap-error); 
        background: rgba(248, 113, 113, 0.1);
    }
`;
document.head.appendChild(style);

function applyHighlights(text) {
    // Escape HTML to prevent XSS
    let html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    const tokens = [];
    let tokenIndex = 0;

    function saveToken(markup) {
        const id = `@@TOKEN_${tokenIndex++}@@`;
        tokens.push({ id, markup });
        return id;
    }

    // A. Improved LoRA Parsing
    const loraRegex = /(&lt;lora:)([^:&>]+)((?::[^:&>]*){0,3})(&gt;)/gi;
    html = html.replace(loraRegex, (match, open, name, args, close) => {
        let res = `<span class="ap-lora">${open}</span>`;
        res += `<span class="ap-lora-name">${name}</span>`;

        const parts = args.split(':');
        const classes = ['ap-lora-x', 'ap-lora-y', 'ap-lora-z'];

        for (let i = 1; i < parts.length; i++) {
            const val = parts[i];
            res += `<span class="ap-lora">:</span>`;
            if (val.length > 0) {
                res += `<span class="${classes[i - 1] || 'ap-lora'}">${val}</span>`;
            }
        }
        res += `<span class="ap-lora">${close}</span>`;
        return saveToken(res);
    });

    // B. Wildcards + Variables
    const wildcardRegex = /__(?:([A-Za-z0-9_\-/\*\.~]+))?(?:\^([A-Za-z0-9_\-\*]+))?__/g;
    html = html.replace(wildcardRegex, (match, name, variable) => {
        if (variable && !name) {
            return saveToken(`<span class="ap-wildcard-var">${match}</span>`);
        }
        return saveToken(`<span class="ap-wildcard">${match}</span>`);
    });

    // C. Integrated Bracket & Separator Parsing
    let chars = html.split('');
    let bracketStack = [];

    for (let i = 0; i < chars.length; i++) {
        // 1. Handle Brackets
        if (chars[i] === '{') {
            bracketStack.push(i);
            chars[i] = `<span class="ap-bracket">{</span>`;
        }
        else if (chars[i] === '}') {
            if (bracketStack.length > 0) {
                bracketStack.pop();
                chars[i] = `<span class="ap-bracket">}</span>`;
            } else {
                chars[i] = `<span class="ap-error">}</span>`;
            }
        }
        // 2. Handle Separators (ONLY if inside a bracket)
        else if (bracketStack.length > 0) {
            // Check for multi-char separators first ($$ or ??)
            const lookahead2 = chars[i] + (chars[i + 1] || '');
            if (lookahead2 === '$$' || lookahead2 === '??') {
                chars[i] = `<span class="ap-bracket">${lookahead2}</span>`;
                chars[i + 1] = ''; // Nullify the second character
                i++; // Skip next char
            }
            // Check for single-char separator (|)
            else if (chars[i] === '|') {
                chars[i] = `<span class="ap-bracket">|</span>`;
            }
        }
    }

    // Handle dangling opening brackets
    while (bracketStack.length > 0) {
        let openIndex = bracketStack.pop();
        // Since we already replaced the char at openIndex with the span string, 
        // we need to wrap the existing span in an error class or modify it
        chars[openIndex] = chars[openIndex].replace('ap-bracket', 'ap-error');
    }

    html = chars.join('');

    // D. Restore Tokens
    for (let i = tokens.length - 1; i >= 0; i--) {
        html = html.replace(tokens[i].id, tokens[i].markup);
    }

    return html;
}

// --- 3. WIDGET INJECTION ---
app.registerExtension({
    name: "AdaptivePrompts.Highlighter",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        const onNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);

            const validClasses = ["PromptGen", "PromptSequencer", "PromptRe", "PromptLora", "PromptMix"];
            if (!this.comfyClass || !validClasses.some(x => this.comfyClass.includes(x))) return;

            for (const widget of this.widgets || []) {
                if (widget.type === "customtext" || (widget.type === "text" && widget.element?.nodeName === "TEXTAREA")) {
                    const textarea = widget.element;
                    if (!textarea || textarea.classList.contains("ap-editor-textarea")) continue;

                    const setupMirrorPattern = () => {
                        const parent = textarea.parentNode;
                        if (!parent) {
                            requestAnimationFrame(setupMirrorPattern);
                            return;
                        }

                        const container = document.createElement("div");
                        container.className = "ap-editor-container";
                        const backdrop = document.createElement("div");
                        backdrop.className = "ap-editor-backdrop";

                        parent.insertBefore(container, textarea);
                        container.appendChild(backdrop);
                        container.appendChild(textarea);
                        textarea.classList.add("ap-editor-textarea");

                        const updateHighlight = () => {
                            backdrop.innerHTML = applyHighlights(textarea.value);
                        };

                        const syncScroll = () => {
                            backdrop.scrollTop = textarea.scrollTop;
                            backdrop.scrollLeft = textarea.scrollLeft;
                        };

                        textarea.addEventListener("input", updateHighlight);
                        textarea.addEventListener("scroll", syncScroll);
                        updateHighlight();
                    };
                    setupMirrorPattern();
                }
            }
        };
    }
});