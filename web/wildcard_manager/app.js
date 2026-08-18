const API = "/adaptiveprompts/api";
const RECENTS_SENTINEL = "__recents__";
const RECENTS_KEY = "ap_recent_files";
const RECENTS_MAX = 30;
let originalEditorContent = "";

const state = {
    folderTree: [],
    expandedNodes: new Set(),
    activeFolder: null,
    currentPath: "",
    activeFile: null,
    lastSavedContent: null,
};

// ---------- console ----------
function log(message, isError = false) {
    const body = document.getElementById("ap-console-body");
    const line = document.createElement("div");
    line.className = "ap-log-line" + (isError ? " ap-log-error" : "");
    line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ---------- api helpers ----------
async function apiGet(path) {
    const res = await fetch(`${API}${path}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
}
async function apiSend(path, body, method = "POST") {
    const res = await fetch(`${API}${path}`, {
        method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
}

// ---------- recents (localStorage) ----------
function getRecents() {
    try { return JSON.parse(localStorage.getItem(RECENTS_KEY)) || []; }
    catch { return []; }
}
function saveRecents(list) {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(list));
}
function recordRecent(file) {
    let recents = getRecents();
    recents = recents.filter(r => !(r.folder === file.folder && r.relPath === file.relPath && r.type === file.type));
    recents.unshift({ folder: file.folder, relPath: file.relPath, type: file.type, name: file.name, hasPreview: !!file.hasPreview, description: file.description || null });
    if (recents.length > RECENTS_MAX) recents.length = RECENTS_MAX;
    saveRecents(recents);
}
function removeFromRecents(file) {
    const recents = getRecents().filter(r => !(r.folder === file.folder && r.relPath === file.relPath && r.type === file.type));
    saveRecents(recents);
}
function clearRecents() {
    localStorage.removeItem(RECENTS_KEY);
}

// ---------- editor panel toggle ----------
let editorOpen = false;
let isResizing = false;

function setEditorOpen(open) {
    editorOpen = open;
    const panel = document.getElementById("ap-editor-panel");
    const resizer = document.getElementById("ap-resizer");

    if (open) {
        panel.classList.remove("collapsed");
        resizer.classList.remove("hidden");
        if (!panel.style.width) panel.style.width = "1280px";
    } else {
        panel.classList.add("collapsed");
        resizer.classList.add("hidden");
        panel.style.width = "";

        // ADD THIS: Remove highlight when closing the editor panel
        document.querySelectorAll('.ap-card').forEach(c => c.classList.remove('active-editing'));
    }

    document.querySelector("#ap-editor-toggle i").className = `pi ${open ? "pi-angle-double-right" : "pi-angle-double-left"}`;
}

document.getElementById("ap-editor-toggle").onclick = () => setEditorOpen(!editorOpen);

// Resizer logic
const resizerHandle = document.getElementById("ap-resizer");
resizerHandle.addEventListener("mousedown", (e) => {
    isResizing = true;
    resizerHandle.classList.add("active");
    document.body.style.cursor = "col-resize";
    e.preventDefault();
});
document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const containerRect = document.body.getBoundingClientRect();
    let newWidth = containerRect.right - e.clientX;
    if (newWidth < 280) newWidth = 280;
    if (newWidth > containerRect.width - 300) newWidth = containerRect.width - 300;
    document.getElementById("ap-editor-panel").style.width = `${newWidth}px`;
});
document.addEventListener("mouseup", () => {
    if (isResizing) {
        isResizing = false;
        resizerHandle.classList.remove("active");
        document.body.style.cursor = "";
    }
});

// ---------- folder tree ----------
async function loadFolderTree() {
    try {
        const data = await apiGet("/folder-tree");
        state.folderTree = data.tree;
        if (!state.activeFolder && state.folderTree.length) {
            state.activeFolder = state.folderTree[0].label;
            state.expandedNodes.add(`${state.activeFolder}::`);
        }
        renderFolderTree();
        loadFiles();
    } catch (e) {
        log(`Failed to load folder tree: ${e.message}`, true);
    }
}

function renderFolderTree() {
    const container = document.getElementById("ap-folder-tree");
    container.innerHTML = "";
    container.appendChild(buildRecentsNode());
    for (const rootNode of state.folderTree) {
        container.appendChild(buildTreeNode(rootNode.label, rootNode.label, "", rootNode.children, 0));
    }
}

function buildRecentsNode() {
    const li = document.createElement("li");
    li.className = "ap-tree-node";

    const row = document.createElement("div");
    row.className = "ap-tree-row" + (state.activeFolder === RECENTS_SENTINEL ? " active" : "");
    row.style.paddingLeft = "8px";
    row.innerHTML = `
        <span class="ap-tree-toggle-spacer"></span>
        <i class="pi pi-history ap-tree-icon"></i>
        <span class="ap-tree-label">Recents</span>
    `;

    row.onclick = () => {
        state.activeFolder = RECENTS_SENTINEL;
        state.currentPath = "";
        renderFolderTree();
        loadFiles();
    };
    row.oncontextmenu = (e) => showRecentsContextMenu(e);

    li.appendChild(row);
    return li;
}

function showRecentsContextMenu(e) {
    e.preventDefault();
    e.stopPropagation();
    const menu = document.getElementById("ap-context-menu");
    menu.innerHTML = "";

    const clearBtn = document.createElement("button");
    clearBtn.innerHTML = "<i class='pi pi-trash'></i> Clear History";
    clearBtn.onclick = () => {
        hideContextMenu();
        if (!confirm("Clear recent files history? This only clears the list, not the files themselves.")) return;
        clearRecents();
        log("Cleared recent files history.");
        if (state.activeFolder === RECENTS_SENTINEL) loadFiles();
    };
    menu.appendChild(clearBtn);

    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;
    menu.style.display = "block";
}

function buildTreeNode(displayName, categoryLabel, path, children, depth) {
    const key = `${categoryLabel}::${path}`;
    const hasChildren = !!(children && children.length);
    const isExpanded = state.expandedNodes.has(key);

    const li = document.createElement("li");
    li.className = "ap-tree-node";

    const row = document.createElement("div");
    row.className = "ap-tree-row" + (state.activeFolder === categoryLabel && state.currentPath === path ? " active" : "");
    row.style.paddingLeft = `${8 + depth * 14}px`;

    const toggle = document.createElement("span");
    toggle.className = "ap-tree-toggle";
    if (hasChildren) {
        toggle.innerHTML = `<i class="pi ${isExpanded ? "pi-chevron-down" : "pi-chevron-right"}"></i>`;
        toggle.onclick = (e) => {
            e.stopPropagation();
            if (isExpanded) state.expandedNodes.delete(key);
            else state.expandedNodes.add(key);
            renderFolderTree();
        };
    } else {
        toggle.innerHTML = `<span class="ap-tree-toggle-spacer"></span>`;
    }
    row.appendChild(toggle);

    const icon = document.createElement("i");
    icon.className = `pi ${isExpanded && hasChildren ? "pi-folder-open" : "pi-folder"} ap-tree-icon`;
    row.appendChild(icon);

    const label = document.createElement("span");
    label.className = "ap-tree-label";
    label.textContent = displayName;
    row.appendChild(label);

    row.onclick = () => {
        state.activeFolder = categoryLabel;
        state.currentPath = path;
        renderFolderTree();
        loadFiles();
    };
    row.oncontextmenu = (e) => showFolderContextMenu(e, categoryLabel, path, depth);

    li.appendChild(row);

    if (hasChildren && isExpanded) {
        const ul = document.createElement("ul");
        ul.className = "ap-tree-children";
        for (const child of children) {
            const childPath = path ? `${path}/${child.name}` : child.name;
            ul.appendChild(buildTreeNode(child.name, categoryLabel, childPath, child.children, depth + 1));
        }
        li.appendChild(ul);
    }
    return li;
}

// ---------- folder context menu ----------
function showFolderContextMenu(e, categoryLabel, subPath, depth) {
    e.preventDefault();
    e.stopPropagation();
    const menu = document.getElementById("ap-context-menu");
    menu.innerHTML = "";

    const revealBtn = document.createElement("button");
    revealBtn.innerHTML = "<i class='pi pi-external-link'></i> Reveal in OS";
    revealBtn.onclick = () => {
        hideContextMenu();
        revealInExplorer(categoryLabel, subPath);
    };
    menu.appendChild(revealBtn);

    const addBtn = document.createElement("button");
    addBtn.innerHTML = "<i class='pi pi-folder-plus'></i> New Folder…";
    addBtn.onclick = async () => {
        hideContextMenu();
        const name = prompt("New subfolder name:");
        if (!name) return;
        try {
            await apiSend("/folder/create-sub", { folder: categoryLabel, path: subPath, name });
            log(`Created folder "${name}"`);
            state.expandedNodes.add(`${categoryLabel}::${subPath}`);
            loadFolderTree();
        } catch (err) { log(`Failed to create folder: ${err.message}`, true); }
    };
    menu.appendChild(addBtn);

    const renameBtn = document.createElement("button");
    renameBtn.innerHTML = "<i class='pi pi-pencil'></i> Rename…";
    const isProtectedRoot = depth === 0 && categoryLabel === "wildcards" && subPath === "";
    if (isProtectedRoot) {
        renameBtn.disabled = true;
        renameBtn.style.opacity = "0.4";
        renameBtn.title = "The default 'wildcards' folder can't be renamed";
    } else {
        renameBtn.onclick = async () => {
            hideContextMenu();
            const currentName = subPath === "" ? categoryLabel : subPath.split("/").pop();
            const newName = prompt("Rename folder to:", currentName);
            if (!newName || newName === currentName) return;
            try {
                await apiSend("/folder/rename", { folder: categoryLabel, path: subPath, newName });
                log(`Renamed "${currentName}" to "${newName}"`);
                if (state.activeFolder === categoryLabel && state.currentPath.startsWith(subPath)) {
                    state.activeFolder = null;
                    state.currentPath = "";
                }
                loadFolderTree();
            } catch (err) { log(`Failed to rename folder: ${err.message}`, true); }
        };
    }
    menu.appendChild(renameBtn);

    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;
    menu.style.display = "block";
}
function hideContextMenu() { document.getElementById("ap-context-menu").style.display = "none"; }
document.addEventListener("click", hideContextMenu);
document.getElementById("ap-add-folder").onclick = async () => {
    const name = prompt("New folder name (creates wildcards_<name>):");
    if (!name) return;
    try { await apiSend("/folders", { name }); log(`Created folder wildcards_${name}`); loadFolderTree(); }
    catch (err) { log(`Failed to create folder: ${err.message}`, true); }
};

// ---------- files / cards ----------
async function loadFiles() {
    if (!state.activeFolder) return;

    if (state.activeFolder === RECENTS_SENTINEL) {
        renderBreadcrumb();
        renderFileGrid(getRecents());
        return;
    }

    try {
        const data = await apiGet(`/files?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(state.currentPath)}`);
        const files = data.files.map(f => ({ ...f, folder: state.activeFolder }));
        renderBreadcrumb();
        renderFileGrid(files);
    } catch (e) {
        log(`Failed to load files: ${e.message}`, true);
    }
}

function renderBreadcrumb() {
    const el = document.getElementById("ap-breadcrumb");
    el.innerHTML = "";

    if (state.activeFolder === RECENTS_SENTINEL) {
        const span = document.createElement("span");
        span.textContent = "Recents";
        el.appendChild(span);
        return;
    }

    const rootSpan = document.createElement("span");
    rootSpan.textContent = state.activeFolder;
    rootSpan.onclick = () => { state.currentPath = ""; renderFolderTree(); loadFiles(); };
    el.appendChild(rootSpan);

    let accum = "";
    for (const part of state.currentPath ? state.currentPath.split("/") : []) {
        accum = accum ? `${accum}/${part}` : part;
        el.appendChild(document.createTextNode(" / "));
        const span = document.createElement("span");
        span.textContent = part;
        const target = accum;
        span.onclick = () => { state.currentPath = target; renderFolderTree(); loadFiles(); };
        el.appendChild(span);
    }
}

function renderFileGrid(files) {
    const grid = document.getElementById("ap-file-grid");
    grid.innerHTML = "";

    for (const file of files) {
        const card = document.createElement("div");
        card.className = "ap-card";

        // NEW: Create a reliable identifier for targeting the card later
        const filepath = `${file.folder}/${file.relPath}.${file.type}`;
        card.setAttribute('data-filepath', filepath);

        card.title = file.description
            ? `${filepath}\n\n${file.description}`
            : filepath;
        if (state.activeFile && state.activeFile.folder === file.folder && state.activeFile.relPath === file.relPath && state.activeFile.type === file.type) {
            card.classList.add('active-editing');
        }
        if (file.hasPreview) {
            card.style.backgroundImage = `url('${API}/preview?folder=${encodeURIComponent(file.folder)}&path=${encodeURIComponent(file.relPath)}&t=${Date.now()}')`;
        }

        const displayName = file.displayname || file.name;
        const nameColorStyle = (file.color && file.color.toUpperCase() !== "#FFFFFF") ? `style="color: ${file.color};"` : "";
        const typeClass = file.type === "json" ? "ap-badge-json" : "ap-badge-txt";
        const descriptionHtml = file.description
            ? `<div class="ap-card-description">${escapeHtml(file.description)}</div>`
            : '';
        //                <button data-action="edit" title="Edit"><i class="pi pi-pencil"></i></button>
        card.innerHTML = `
            <div class="ap-card-toolbar">
                <button data-action="preview" title="Add Preview"><i class="pi pi-image"></i></button>
                <button data-action="reveal" title="Reveal in OS"><i class="pi pi-external-link"></i></button>
                <button data-action="copy" title="Copy wildcard reference"><i class="pi pi-copy"></i></button>
                <button data-action="generate" title="Generate"><i class="pi pi-bolt"></i></button>
            </div>
            <input type="file" accept="image/png" class="ap-preview-input" style="display:none;">
            <div class="ap-card-footer">
                ${descriptionHtml}
                <div class="ap-card-footer-row">
                    <span class="ap-card-name" ${nameColorStyle}>${displayName}</span>
                    <span class="ap-card-type ${typeClass}">${file.type.toUpperCase()}</span>
                </div>
            </div>
        `;

        //card.querySelector('[data-action="edit"]').onclick = () => openEditor(file);
        card.querySelector('[data-action="generate"]').onclick = () => quickGenerate(file);
        card.querySelector('[data-action="copy"]').onclick = () => copyWildcardRef(file);
        card.querySelector('[data-action="reveal"]').onclick = () => revealInExplorer(file.folder, file.relPath, file.type);
        const fileInput = card.querySelector(".ap-preview-input");
        card.querySelector('[data-action="preview"]').onclick = () => fileInput.click();
        fileInput.onchange = () => uploadPreview(file, fileInput.files[0]);

        card.addEventListener('click', (e) => {
            if (e.target.closest('.ap-card-toolbar') || e.target.closest('.ap-preview-input')) return;
            openEditor(file);
        });

        card.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            showFileContextMenu(e, file);
        });

        grid.appendChild(card);
    }
}

async function copyWildcardRef(file) {
    const ref = `__${file.relPath}__`;
    try {
        await navigator.clipboard.writeText(ref);
        log(`Copied ${ref} to clipboard`);
    } catch (e) {
        log(`Copy failed: ${e.message}`, true);
    }
}

async function uploadPreview(file, blob) {
    if (!blob) return;
    const formData = new FormData();
    formData.append("folder", file.folder);
    formData.append("path", file.relPath);
    formData.append("image", blob);

    try {
        const res = await fetch(`${API}/preview`, { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        log(`Preview updated for ${file.relPath}`);

        const recents = getRecents();
        const match = recents.find(r => r.folder === file.folder && r.relPath === file.relPath && r.type === file.type);
        if (match) { match.hasPreview = true; saveRecents(recents); }

        loadFiles();
    } catch (e) {
        log(`Preview upload failed: ${e.message}`, true);
    }
}

// ---------- editor ----------
async function openEditor(file) {
    // Prevent reloading if clicking the already active file
    if (state.activeFile && state.activeFile.folder === file.folder && state.activeFile.relPath === file.relPath && state.activeFile.type === file.type) {
        return;
    }

    const textarea = document.getElementById("ap-editor-textarea");

    // Force sync from builder to raw so we can accurately check for changes
    if (state.activeFile && state.activeFile.type === "json" && typeof JSONBuilder !== 'undefined') {
        JSONBuilder.syncToRaw();
    }

    // Intercept if dirtied
    if (state.activeFile && state.lastSavedContent !== null) {
        if (textarea.value !== state.lastSavedContent) {
            UnsavedModal.open(
                `${state.activeFile.name}.${state.activeFile.type}`,
                async () => {
                    await editorSave();
                    await performOpenEditor(file);
                },
                async () => {
                    await performOpenEditor(file); // Discard and proceed
                }
            );
            return; // Halt navigation until modal resolves
        }
    }

    await performOpenEditor(file);
}

async function performOpenEditor(file) {
    try {
        const data = await apiGet(`/file?folder=${encodeURIComponent(file.folder)}&path=${encodeURIComponent(file.relPath)}&type=${file.type}`);
        state.activeFile = file;

        document.querySelectorAll('.ap-card').forEach(c => c.classList.remove('active-editing'));

        // FIX: Use the reliable data attribute instead of the title
        const cardPath = `${file.folder}/${file.relPath}.${file.type}`;
        const activeCard = document.querySelector(`.ap-card[data-filepath="${cardPath}"]`);

        if (activeCard) activeCard.classList.add('active-editing');

        document.getElementById("ap-editor-filename").textContent = `${file.folder}/${file.relPath}.${file.type}`;

        const textarea = document.getElementById("ap-editor-textarea");
        textarea.value = data.content;

        const modeToggle = document.getElementById('ap-editor-mode-toggle');
        modeToggle.classList.remove('hidden'); // Keep visible at all times

        const builderBtn = document.querySelector('.ap-mode-btn[data-mode="builder"]');
        const hybridBtn = document.querySelector('.ap-mode-btn[data-mode="hybrid"]');

        if (file.type === "json") {
            if (builderBtn) builderBtn.disabled = false;
            if (hybridBtn) hybridBtn.disabled = false;

            JSONBuilder.open(data.content);
            JSONBuilder.syncToRaw();
        } else {
            if (builderBtn) builderBtn.disabled = true;
            if (hybridBtn) hybridBtn.disabled = true;

            JSONBuilder.close();
            document.getElementById('ap-editor-content-area').className = 'ap-content-raw';
            JSONBuilder.updateRawHighlighting(data.content);
        }

        // NEW: Take the snapshot AFTER the formatting finishes, ensuring a 1:1 match
        state.lastSavedContent = textarea.value;

        setEditorOpen(true);
        recordRecent(file);
    } catch (e) {
        log(`Failed to open ${file.relPath}: ${e.message}`, true);
    }
}

async function editorSave() {
    if (!state.activeFile) return;

    const textarea = document.getElementById("ap-editor-textarea");
    if (state.activeFile.type === "json" && (JSONBuilder.mode === "raw" || JSONBuilder.mode === "hybrid")) {
        JSONBuilder.syncFromRaw(textarea.value);
    }

    try {
        await apiSend("/file", {
            folder: state.activeFile.folder,
            path: state.activeFile.relPath,
            type: state.activeFile.type,
            content: textarea.value,
        });
        state.lastSavedContent = textarea.value;
        log(`Saved ${state.activeFile.relPath}.${state.activeFile.type}`);
        flashSaved();

        if (state.activeFile.type === "json") {
            try {
                const parsed = JSON.parse(textarea.value);
                const newDesc = (parsed && typeof parsed.description === 'string') ? parsed.description.trim() : "";
                const newDisp = (parsed && typeof parsed.displayname === 'string') ? parsed.displayname.trim() : "";
                const newColor = (parsed && typeof parsed.color === 'string') ? parsed.color.trim() : "";

                state.activeFile.description = newDesc;
                state.activeFile.displayname = newDisp;
                state.activeFile.color = newColor;

                const cardPath = `${state.activeFile.folder}/${state.activeFile.relPath}.${state.activeFile.type}`;
                const card = document.querySelector(`.ap-card[data-filepath="${cardPath}"]`);

                if (card) {
                    card.title = newDesc ? `${cardPath}\n\n${newDesc}` : cardPath;

                    let descEl = card.querySelector('.ap-card-description');
                    // ... [existing description element updates] ...

                    // Update Display Name and Color visually
                    let nameEl = card.querySelector('.ap-card-name');
                    if (nameEl) {
                        nameEl.textContent = newDisp || state.activeFile.name;
                        if (newColor && newColor.toUpperCase() !== "#FFFFFF") {
                            nameEl.style.color = newColor;
                        } else {
                            nameEl.style.color = ""; // reset to default
                        }
                    }
                }
            } catch (err) { }
        }

    } catch (e) {
        log(`Failed to save: ${e.message}`, true);
    }
}
document.getElementById("ap-editor-save").onclick = editorSave;

function flashSaved() {
    const panel = document.getElementById("ap-editor-panel");
    panel.classList.remove("ap-flash-save");
    void panel.offsetWidth;
    panel.classList.add("ap-flash-save");
}

async function editorGenerate() {
    if (!state.activeFile) return;
    await editorSave();
    quickGenerate(state.activeFile);
}
document.getElementById("ap-editor-generate").onclick = editorGenerate;

// ---------- quick generate (shared by cards + editor) ----------
async function quickGenerate(file) {
    const seed = parseInt(document.getElementById("ap-seed-input").value, 10);
    try {
        const data = await apiSend("/generate", {
            folder: file.folder, path: file.relPath,
            seed: Number.isFinite(seed) ? seed : -1,
        });
        log(`__${file.relPath}__ (seed ${data.seed}) → ${data.result}`);
    } catch (e) {
        log(`Generate failed for ${file.relPath}: ${e.message}`, true);
    }
}

// ---------- keybinds ----------
document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); editorSave(); }
    else if (mod && e.key === "Enter") { e.preventDefault(); editorGenerate(); }
});

// ---------- file context menu (card right click) ----------
function showFileContextMenu(e, file) {
    const menu = document.getElementById("ap-context-menu");
    menu.innerHTML = "";

    const editBtn = document.createElement("button");
    editBtn.innerHTML = "<i class='pi pi-pencil'></i> Edit";
    editBtn.onclick = () => { hideContextMenu(); openEditor(file); };
    menu.appendChild(editBtn);

    // Add this right after the editBtn is appended
    const revealBtn = document.createElement("button");
    revealBtn.innerHTML = "<i class='pi pi-external-link'></i> Reveal in OS";
    revealBtn.onclick = () => { hideContextMenu(); revealInExplorer(file.folder, file.relPath, file.type); };
    menu.appendChild(revealBtn);

    const previewBtn = document.createElement("button");
    previewBtn.innerHTML = "<i class='pi pi-image'></i> Add Preview";
    previewBtn.onclick = () => {
        hideContextMenu();
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/png";
        input.onchange = () => {
            if (input.files && input.files.length > 0) {
                uploadPreview(file, input.files[0]);
            }
        };
        input.click();
    };
    menu.appendChild(previewBtn);

    const divider = document.createElement("hr");
    divider.style.borderColor = "var(--ap-border)";
    divider.style.margin = "4px 0";
    menu.appendChild(divider);

    const dupBtn = document.createElement("button");
    dupBtn.innerHTML = "<i class='pi pi-copy'></i> Duplicate";
    dupBtn.onclick = async () => {
        hideContextMenu();
        try {
            const data = await apiGet(`/file?folder=${encodeURIComponent(file.folder)}&path=${encodeURIComponent(file.relPath)}&type=${file.type}`);

            let newPath = file.relPath;
            const match = newPath.match(/_(\d+)$/);
            if (match) {
                newPath = newPath.substring(0, match.index) + '_' + (parseInt(match[1]) + 1);
            } else {
                newPath += "_1";
            }

            // Check config to prompt for rename
            if (typeof SettingsManager !== 'undefined' && SettingsManager.config && SettingsManager.config.rename_on_duplicate) {
                const userPath = prompt(`Enter name for duplicated file:`, newPath);
                if (!userPath) return; // Cancel duplicate entirely
                newPath = userPath;
            }

            await apiSend("/file", { folder: file.folder, path: newPath, type: file.type, content: data.content });
            log(`Duplicated file as ${newPath}`);
            loadFiles();
        } catch (err) { log(`Failed to duplicate: ${err.message}`, true); }
    };
    menu.appendChild(dupBtn);

    const renBtn = document.createElement("button");
    renBtn.innerHTML = "<i class='pi pi-file-edit'></i> Rename";
    renBtn.onclick = () => { hideContextMenu(); RenameFileModal.open(file); };
    menu.appendChild(renBtn);

    const delBtn = document.createElement("button");
    delBtn.innerHTML = "<i class='pi pi-trash'></i> Delete";
    delBtn.style.color = "var(--ap-danger)";
    delBtn.onclick = async () => {
        hideContextMenu();
        if (!confirm(`Are you sure you want to delete ${file.relPath}.${file.type}?`)) return;
        try {
            const result = await apiSend(`/file?folder=${encodeURIComponent(file.folder)}&path=${encodeURIComponent(file.relPath)}&type=${file.type}`, {}, "DELETE");
            log(`Deleted ${file.relPath} (${result.method})`);
            removeFromRecents(file);
            if (state.activeFile && state.activeFile.folder === file.folder && state.activeFile.relPath === file.relPath) setEditorOpen(false);
            loadFiles();
        } catch (err) { log(`Failed to delete: ${err.message}`, true); }
    };
    menu.appendChild(delBtn);

    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;
    menu.style.display = "block";
}

// ---------- top nav buttons ----------
document.getElementById("ap-btn-refresh").onclick = () => {
    loadFolderTree();
    log("Refreshed wildcard structural data.");
};

document.getElementById("ap-btn-new-file").onclick = () => {
    if (!state.activeFolder || state.activeFolder === RECENTS_SENTINEL) {
        alert("Please select a folder first.");
        return;
    }
    NewFileModal.open(state.currentPath || "");
};

const NewFileModal = {
    currentPath: '',
    selectedType: localStorage.getItem('ap_new_file_type') || 'json',

    init() {
        this.updateToggleUI();
        document.getElementById('ap-toggle-txt').onclick = () => this.setType('txt');
        document.getElementById('ap-toggle-json').onclick = () => this.setType('json');

        const input = document.getElementById('ap-new-file-input');
        input.oninput = () => this.updatePreview();
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.confirm();
            if (e.key === 'Escape') this.close();
        });

        document.getElementById('ap-new-file-cancel').onclick = () => this.close();
        document.getElementById('ap-new-file-backdrop').onclick = () => this.close();
        document.getElementById('ap-new-file-confirm').onclick = () => this.confirm();
    },

    open(folderPath) {
        this.currentPath = folderPath;
        const input = document.getElementById('ap-new-file-input');
        input.value = '';
        this.updatePreview();
        document.getElementById('ap-new-file-modal').classList.remove('hidden');
        input.focus();
    },

    close() { document.getElementById('ap-new-file-modal').classList.add('hidden'); },

    setType(type) {
        this.selectedType = type;
        localStorage.setItem('ap_new_file_type', type);
        this.updateToggleUI();
    },

    updateToggleUI() {
        const btnTxt = document.getElementById('ap-toggle-txt');
        const btnJson = document.getElementById('ap-toggle-json');
        if (this.selectedType === 'txt') { btnTxt.classList.add('active'); btnJson.classList.remove('active'); }
        else { btnTxt.classList.remove('active'); btnJson.classList.add('active'); }
    },

    updatePreview() {
        const inputVal = document.getElementById('ap-new-file-input').value.trim();
        const previewEl = document.getElementById('ap-new-file-preview');
        if (!inputVal) { previewEl.textContent = ''; return; }

        let cleanPath = this.currentPath.replace(/^[\/\\]*(wildcards)?[\/\\]*/i, '');
        if (cleanPath && !cleanPath.endsWith('/')) cleanPath += '/';
        previewEl.textContent = `__${cleanPath}${inputVal}__`;
    },

    async confirm() {
        const filename = document.getElementById('ap-new-file-input').value.trim();
        if (!filename) return;
        const cleanFileName = filename.replace(/\.(json|txt)$/i, '');
        const fullPath = this.currentPath ? `${this.currentPath}/${cleanFileName}` : cleanFileName;

        try {
            const initialContent = this.selectedType === 'json'
                ? '{\n    "variables": {},\n    "loras": [],\n    "generate": []\n}'
                : '';

            await apiSend("/file", { folder: state.activeFolder, path: fullPath, type: this.selectedType, content: initialContent });
            log(`Created ${cleanFileName}.${this.selectedType}`);
            this.close();
            loadFiles();
        } catch (e) {
            log(`Failed to create file: ${e.message}`, true);
        }
    }
};

const RenameFileModal = {
    file: null,
    dirPrefix: '',

    init() {
        const input = document.getElementById('ap-rename-file-input');
        input.oninput = () => this.updatePreview();
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.confirm();
            if (e.key === 'Escape') this.close();
        });

        document.getElementById('ap-rename-file-cancel').onclick = () => this.close();
        document.getElementById('ap-rename-file-backdrop').onclick = () => this.close();
        document.getElementById('ap-rename-file-confirm').onclick = () => this.confirm();
    },

    open(file) {
        this.file = file;
        const lastSlash = file.relPath.lastIndexOf('/');
        this.dirPrefix = lastSlash >= 0 ? file.relPath.substring(0, lastSlash + 1) : '';
        const baseName = lastSlash >= 0 ? file.relPath.substring(lastSlash + 1) : file.relPath;

        document.getElementById('ap-rename-file-prefix').textContent = this.dirPrefix;
        const input = document.getElementById('ap-rename-file-input');
        input.value = baseName;
        this.updatePreview();

        document.getElementById('ap-rename-file-modal').classList.remove('hidden');
        input.focus();
        input.select();
    },

    close() {
        document.getElementById('ap-rename-file-modal').classList.add('hidden');
        this.file = null;
    },

    updatePreview() {
        const baseName = document.getElementById('ap-rename-file-input').value.trim();
        document.getElementById('ap-rename-file-preview').textContent = baseName ? `__${this.dirPrefix}${baseName}__` : '';
    },

    async confirm() {
        if (!this.file) return;
        const baseName = document.getElementById('ap-rename-file-input').value.trim().replace(/\.(json|txt)$/i, '');
        if (!baseName) return;

        const newPath = `${this.dirPrefix}${baseName}`;
        if (newPath === this.file.relPath) { this.close(); return; }

        try {
            const data = await apiGet(`/file?folder=${encodeURIComponent(this.file.folder)}&path=${encodeURIComponent(this.file.relPath)}&type=${this.file.type}`);
            await apiSend("/file", { folder: this.file.folder, path: newPath, type: this.file.type, content: data.content });
            await apiSend(`/file?folder=${encodeURIComponent(this.file.folder)}&path=${encodeURIComponent(this.file.relPath)}&type=${this.file.type}`, {}, "DELETE");

            log(`Renamed to ${newPath}.${this.file.type}`);
            removeFromRecents(this.file);
            const wasOpen = state.activeFile && state.activeFile.folder === this.file.folder && state.activeFile.relPath === this.file.relPath;
            this.close();
            if (wasOpen) setEditorOpen(false);
            loadFiles();
        } catch (err) {
            log(`Failed to rename: ${err.message}`, true);
        }
    }
};

// ---------- init ----------
document.addEventListener('DOMContentLoaded', () => {
    NewFileModal.init();
    RenameFileModal.init();
});
loadFolderTree();
log("Wildcard Manager ready.");

const UnsavedModal = {
    onConfirm: null,
    onDiscard: null,

    init() {
        document.getElementById('ap-unsaved-cancel').onclick = () => this.close();
        document.getElementById('ap-unsaved-backdrop').onclick = () => this.close();
        document.getElementById('ap-unsaved-confirm').onclick = () => this.confirm();
        document.getElementById('ap-unsaved-discard').onclick = () => this.discard();

        document.addEventListener('keydown', (e) => {
            const modal = document.getElementById('ap-unsaved-modal');
            if (!modal.classList.contains('hidden')) {
                if (e.key === 'Enter') { e.preventDefault(); this.confirm(); }
                if (e.key === 'Escape') { e.preventDefault(); this.close(); }
            }
        });
    },
    open(filename, onConfirm, onDiscard) {
        document.getElementById('ap-unsaved-filename').textContent = filename;
        this.onConfirm = onConfirm;
        this.onDiscard = onDiscard;
        document.getElementById('ap-unsaved-modal').classList.remove('hidden');
    },
    close() {
        document.getElementById('ap-unsaved-modal').classList.add('hidden');
        this.onConfirm = null;
        this.onDiscard = null;
    },
    confirm() {
        if (this.onConfirm) this.onConfirm();
        this.close();
    },
    discard() {
        if (this.onDiscard) this.onDiscard();
        this.close();
    }
};

document.addEventListener('DOMContentLoaded', () => {
    NewFileModal.init();
    RenameFileModal.init();
    UnsavedModal.init(); // <--- ADD THIS
});


async function revealInExplorer(folder, path, type = "") {
    try {
        await apiSend("/reveal", { folder, path, type });
        log(`Revealed in OS Explorer`);
    } catch (e) {
        log(`Failed to reveal: ${e.message}`, true);
    }
}