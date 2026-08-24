import { app } from "../../scripts/app.js";
import { applyHighlights } from "./adaptive_highlighter_core.js";

const themeLink = document.createElement("link");
themeLink.rel = "stylesheet";
themeLink.type = "text/css";
themeLink.href = new URL("adaptive_theme.css", import.meta.url).href;
document.head.appendChild(themeLink);


// --- 1. CONFIGURABLE COLORS & PLACEMENT FIXES ---
const style = document.createElement("style");
style.innerHTML = `
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
        
        /* FIX 1: Both elements MUST have native scrollbars enabled. 
           Do NOT hide this scrollbar with CSS, otherwise the backdrop 
           gets wider than the textarea and text wraps differently! */
        overflow-y: scroll !important;
        overflow-x: hidden;
        
        white-space: pre-wrap;
        word-wrap: break-word;
        overflow-wrap: break-word;
        
        color: var(--ap-editor-text);
        background: var(--ap-editor-bg);
        pointer-events: none;
        
        /* FIX 2: Strict dimension matching */
        padding: 6px;
        margin: 0;
        box-sizing: border-box;
        border-radius: 4px;
        border: 1px solid transparent; /* Exactly matches textarea border */
        
        font-family: inherit;
        font-size: inherit;
        line-height: inherit;
        letter-spacing: normal;
        text-transform: none;
        font-variant-ligatures: none;
    }

    .ap-editor-textarea {
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        width: 100%; height: 100%;
        
        background: transparent !important;
        color: transparent !important;
        caret-color: white;
        resize: none;
        
        /* FIX 3: Strict dimension matching */
        padding: 6px;
        margin: 0;
        box-sizing: border-box;
        border-radius: 4px;
        border: 1px solid #333;
        outline: none;
        
        font-family: inherit;
        font-size: inherit;
        line-height: inherit;
        letter-spacing: normal;
        text-transform: none;
        font-variant-ligatures: none;
        
        /* Textarea scrollbar perfectly covers the backdrop scrollbar */
        overflow-y: scroll !important;
        overflow-x: hidden;
    }

    /* Visual toggles */
    body.ap-disable-highlighter .ap-editor-backdrop {
        display: none !important;
    }
    body.ap-disable-highlighter .ap-editor-textarea {
        color: inherit !important;
        background: inherit !important;
    }
`;
document.head.appendChild(style);

// --- 2. WIDGET INJECTION ---
app.registerExtension({
    name: "AdaptivePrompts.Highlighter",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        const onNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);

            // Cancels if the feature is disabled
            if (!app.ui.settings.getSettingValue("AdaptivePrompts.enable_highlighter", true)) return;

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