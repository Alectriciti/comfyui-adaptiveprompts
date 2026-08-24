// adaptive_highlighter_core.js
//
// Shared parsing logic for Adaptive Prompts syntax highlighting -- the single
// source of truth for turning raw prompt text into highlighted HTML. Used by
// both the ComfyUI node-editor extension (adaptive_highlighter.js) and the
// Wildcard Manager's Raw text editor (for .txt wildcard files).
//
// Deliberately has ZERO dependency on ComfyUI's `app` or any DOM-mirroring
// logic -- just the pure text-to-HTML transform, so it loads as a plain ES
// module from either context.

export function applyHighlights(text, selfRefName = null, isTxtBuilder = false) {
    let html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    const tokens = [];
    let tokenIndex = 0;

    function saveToken(markup) {
        const id = `@@TOKEN_${tokenIndex++}@@`;
        tokens.push({ id, markup });
        return id;
    }

    // A. Inline Comments (Adaptive Prompts)
    const commentRegex = /##(.*?)##/gs;
    html = html.replace(commentRegex, (match, content) => {
        return saveToken(`<span class="ap-comment">##${content}##</span>`);
    });

    // B. Line Comments (TxtBuilder Only)
    if (isTxtBuilder) {
        // Matches a line starting with # ...
        const lineCommentRegex = /^[ \t]*#.*(?:\r?\n|$)/gm;
        html = html.replace(lineCommentRegex, (match, content) => {
            // FIX: Use 'match' to include the full line (including the #) in the comment span.
            // Previously, we used 'content' which would cut off the leading '#'.
            return saveToken(`<span class="ap-comment">${match}</span>`);
        });
    }

    // C. Improved LoRA Parsing
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

    // D. Wildcards + Variables
    const wildcardRegex = /__(?:([A-Za-z0-9_\-/\*\.~]+))?(?:\^([A-Za-z0-9_\-\*]+))?__/g;
    html = html.replace(wildcardRegex, (match, name, variable) => {
        if (variable && !name) {
            return saveToken(`<span class="ap-wildcard-var">${match}</span>`);
        }

        // Check for self-reference
        if (selfRefName && name === selfRefName) {
            return saveToken(`<span class="ap-wildcard-self">${match}</span>`);
        }

        return saveToken(`<span class="ap-wildcard">${match}</span>`);
    });

    // E. Integrated Bracket & Separator Parsing
    let chars = html.split('');
    let bracketStack = [];

    for (let i = 0; i < chars.length; i++) {
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
        else if (bracketStack.length > 0) {
            const lookahead2 = chars[i] + (chars[i + 1] || '');
            if (lookahead2 === '$$' || lookahead2 === '??') {
                chars[i] = `<span class="ap-bracket">${lookahead2}</span>`;
                chars[i + 1] = '';
                i++;
            }
            else if (chars[i] === '|') {
                chars[i] = `<span class="ap-bracket">|</span>`;
            }
            else if (chars[i] === '%') {
                let numStr = "";
                let step = 1;

                while (i + step < chars.length && /[0-9.]/.test(chars[i + step])) {
                    numStr += chars[i + step];
                    chars[i + step] = '';
                    step++;
                }

                if (numStr.length > 0) {
                    chars[i] = `<span class="ap-prob">%${numStr}</span>`;
                    i += (step - 1);
                }
            }
        }
    }

    if (isTxtBuilder) {
        // Matches % followed by numbers/decimals, allowing for trailing spaces/carriage returns at the end of a line
        const lineEndWeightRegex = /(%[0-9.]+)([ \t\r]*)$/gm;
        html = html.replace(lineEndWeightRegex, (match, weight, spaces) => {
            return saveToken(`<span class="ap-prob">${weight}</span>`) + spaces;
        });
    }

    while (bracketStack.length > 0) {
        let openIndex = bracketStack.pop();
        chars[openIndex] = chars[openIndex].replace('ap-bracket', 'ap-error');
    }

    html = chars.join('');

    const trailingVarRegex = /(<span class="ap-bracket">\}<\/span>)((?:\^[A-Za-z0-9_\-\*]+)+)/g;
    html = html.replace(trailingVarRegex, (match, closeBracket, variables) => {
        return `${closeBracket}<span class="ap-wildcard-var">${variables}</span>`;
    });

    // F. Restore Tokens
    for (let i = tokens.length - 1; i >= 0; i--) {
        html = html.replace(tokens[i].id, tokens[i].markup);
    }

    return html;
}