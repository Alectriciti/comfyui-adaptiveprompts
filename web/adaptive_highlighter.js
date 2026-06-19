import { app } from "../../scripts/app.js";

// --- 1. CONFIGURABLE COLORS ---
const style = document.createElement("style");
style.innerHTML = `
    :root {
        --ap-bracket: #4ade80;       /* Green */
        --ap-wildcard: #22d3ee;      /* Cyan */
        --ap-lora-base: #60a5fa;     /* Blue */
        --ap-lora-x: #c084fc;        /* Pale Purple (Unet) */
        --ap-lora-y: #fde047;        /* Yellow (Clip) */
        --ap-lora-z: #4ade80;        /* Green (Keyword) */
        --ap-error: #f87171;         /* Red */
        
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
        overflow: hidden; /* JS will sync scroll */
        white-space: pre-wrap;
        word-wrap: break-word;
        color: var(--ap-editor-text);
        background: var(--ap-editor-bg);
        pointer-events: none; /* Let clicks pass through to textarea */
        padding: 6px;
        box-sizing: border-box;
        border-radius: 4px;
    }

    .ap-editor-textarea {
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        width: 100%; height: 100%;
        background: transparent !important;
        color: transparent !important; /* Hide real text */
        caret-color: white;            /* Keep cursor visible */
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

    /* Syntax Classes */
    .ap-bracket { color: var(--ap-bracket); font-weight: bold; }
    .ap-wildcard { color: var(--ap-wildcard); }
    .ap-lora { color: var(--ap-lora-base); }
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

// --- 2. PARSING LOGIC ---
function applyHighlights(text) {
    // Escape HTML to prevent XSS and rendering breaks
    let html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    const tokens = [];
    let tokenIndex = 0;

    // Helper to safely stash parsed elements so later regexes don't break them
    function saveToken(markup) {
        const id = `@@TOKEN_${tokenIndex++}@@`;
        tokens.push({ id, markup });
        return id;
    }

    // A. Parse LoRA Tags: <lora:name:x:y:z>
    const loraRegex = /(&lt;lora:[^:&>]+)((?::[^:&>]+)?)((?::[^:&>]+)?)((?::[^:&>]+)?)(&gt;)/gi;
    html = html.replace(loraRegex, (match, base, x, y, z, end) => {
        let res = `<span class="ap-lora">${base}</span>`;
        if (x) res += `<span class="ap-lora-x">${x}</span>`;
        if (y) res += `<span class="ap-lora-y">${y}</span>`;
        if (z) res += `<span class="ap-lora-z">${z}</span>`;
        res += `<span class="ap-lora">${end}</span>`;
        return saveToken(res);
    });

    // B. Parse Valid Wildcards: __name__
    const wildcardRegex = /__[\w\-\/]+__/g;
    html = html.replace(wildcardRegex, match => saveToken(`<span class="ap-wildcard">${match}</span>`));

    // C. Detect Broken Wildcards (Anything starting/ending with underscores that didn't get tokenized above)
    // Matches e.g., __broken_wildcard or broken_wildcard__
    const brokenWildcardRegex = /__[^\s&<]+|[^\s&<]+__/g;
    html = html.replace(brokenWildcardRegex, match => saveToken(`<span class="ap-error">${match}</span>`));

    // D. Stack-based Bracket Parsing (Perfect tracking for nested brackets & errors)
    let chars = html.split('');
    let bracketStack = [];

    for (let i = 0; i < chars.length; i++) {
        if (chars[i] === '{') {
            bracketStack.push(i); // Push index of opening bracket
        } else if (chars[i] === '}') {
            if (bracketStack.length > 0) {
                // Valid Pair
                let openIndex = bracketStack.pop();
                chars[openIndex] = `<span class="ap-bracket">{</span>`;
                chars[i] = `<span class="ap-bracket">}</span>`;
            } else {
                // Unmatched closing bracket -> ERROR
                chars[i] = `<span class="ap-error">}</span>`;
            }
        }
    }

    // Any opening brackets left in the stack were never closed -> ERROR
    while (bracketStack.length > 0) {
        let openIndex = bracketStack.pop();
        chars[openIndex] = `<span class="ap-error">{</span>`;
    }

    html = chars.join('');

    // E. Restore Tokens
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
            if (onNodeCreated) {
                onNodeCreated.apply(this, arguments);
            }

            // 1. RESTRICTION: Only apply to Adaptive Prompts nodes
            // Ensure this matches the class names defined in your Python backend
            const validClasses = [
                "PromptGen",
                "PromptSequencer",
                "PromptRe",
                "PromptLora",
                "PromptMix"
            ];

            if (!this.comfyClass || !validClasses.some(x => this.comfyClass.includes(x))) {
                return;
            }

            // Find multiline text widgets to patch
            for (const widget of this.widgets || []) {
                if (widget.type === "customtext" || (widget.type === "text" && widget.element?.nodeName === "TEXTAREA")) {

                    const textarea = widget.element;
                    if (!textarea || textarea.classList.contains("ap-editor-textarea")) continue;

                    // 2. DEFERRAL: Safely wait for LiteGraph to mount the element
                    const setupMirrorPattern = () => {
                        const parent = textarea.parentNode;

                        if (!parent) {
                            // If it's floating in memory, wait until the next render frame and try again
                            requestAnimationFrame(setupMirrorPattern);
                            return;
                        }

                        // Create wrapper and backdrop
                        const container = document.createElement("div");
                        container.className = "ap-editor-container";

                        const backdrop = document.createElement("div");
                        backdrop.className = "ap-editor-backdrop";

                        // Re-arrange DOM safely
                        parent.insertBefore(container, textarea);
                        container.appendChild(backdrop);
                        container.appendChild(textarea);

                        textarea.classList.add("ap-editor-textarea");

                        // The synchronization engine
                        const updateHighlight = () => {
                            backdrop.innerHTML = applyHighlights(textarea.value);
                        };

                        const syncScroll = () => {
                            backdrop.scrollTop = textarea.scrollTop;
                            backdrop.scrollLeft = textarea.scrollLeft;
                        };

                        // Attach Event Listeners
                        textarea.addEventListener("input", updateHighlight);
                        textarea.addEventListener("scroll", syncScroll);

                        // Trigger initial render
                        updateHighlight();
                    };

                    // Kick off the mounting check
                    setupMirrorPattern();
                }
            }
        };
    }
});