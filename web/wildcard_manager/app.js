const API = "/adaptiveprompts/api";

const state = {
    folderTree: [],
    expandedNodes: new Set(),
    activeFolder: null,
    currentPath: "",
    activeFile: null,
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

// ---------- editor panel toggle ----------
let editorOpen = false;
function setEditorOpen(open) {
    editorOpen = open;
    document.getElementById("ap-editor-panel").classList.toggle("collapsed", !open);
    document.querySelector("#ap-editor-toggle i").className = `pi ${open ? "pi-angle-double-right" : "pi-angle-double-left"}`;
}
document.getElementById("ap-editor-toggle").onclick = () => setEditorOpen(!editorOpen);

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
    for (const rootNode of state.folderTree) {
        container.appendChild(buildTreeNode(rootNode.label, rootNode.label, "", rootNode.children, 0));
    }
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
    if (depth === 0) row.oncontextmenu = (e) => showFolderContextMenu(e, categoryLabel);

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

// ---------- folder context menu (top-level category add/delete) ----------
function showFolderContextMenu(e, label) {
    e.preventDefault();
    const menu = document.getElementById("ap-context-menu");
    menu.innerHTML = "";

    const addBtn = document.createElement("button");
    addBtn.textContent = "New Folder…";
    addBtn.onclick = async () => {
        hideContextMenu();
        const name = prompt("New folder name (creates wildcards_<name>):");
        if (!name) return;
        try { await apiSend("/folders", { name }); log(`Created folder wildcards_${name}`); loadFolderTree(); }
        catch (err) { log(`Failed to create folder: ${err.message}`, true); }
    };
    menu.appendChild(addBtn);

    if (label !== "wildcards") {
        const delBtn = document.createElement("button");
        delBtn.textContent = `Delete "${label}"`;
        delBtn.onclick = async () => {
            hideContextMenu();
            if (!confirm(`Delete empty folder "${label}"? This can't be undone.`)) return;
            try {
                await apiSend(`/folders/${encodeURIComponent(label)}`, {}, "DELETE");
                log(`Deleted folder ${label}`);
                if (state.activeFolder === label) state.activeFolder = null;
                loadFolderTree();
            } catch (err) { log(`Failed to delete folder: ${err.message}`, true); }
        };
        menu.appendChild(delBtn);
    }

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
    try {
        const data = await apiGet(`/files?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(state.currentPath)}`);
        renderBreadcrumb();
        renderFileGrid(data.files);
    } catch (e) {
        log(`Failed to load files: ${e.message}`, true);
    }
}

function renderBreadcrumb() {
    const el = document.getElementById("ap-breadcrumb");
    el.innerHTML = "";
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
        if (file.hasPreview) {
            card.style.backgroundImage = `url('${API}/preview?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(file.relPath)}&t=${Date.now()}')`;
        }

        const typeClass = file.type === "json" ? "ap-badge-json" : "ap-badge-txt";
        card.innerHTML = `
            <div class="ap-card-toolbar">
                <button data-action="preview" title="Add Preview"><i class="pi pi-image"></i></button>
                <button data-action="edit" title="Edit"><i class="pi pi-pencil"></i></button>
                <button data-action="copy" title="Copy wildcard reference"><i class="pi pi-copy"></i></button>
                <button data-action="generate" title="Generate"><i class="pi pi-bolt"></i></button>
            </div>
            <input type="file" accept="image/png" class="ap-preview-input" style="display:none;">
            <div class="ap-card-footer">
                <span class="ap-card-name">${file.name}</span>
                <span class="ap-card-type ${typeClass}">${file.type.toUpperCase()}</span>
            </div>
        `;

        card.querySelector('[data-action="edit"]').onclick = () => openEditor(file);
        card.querySelector('[data-action="generate"]').onclick = () => quickGenerate(file.relPath);
        card.querySelector('[data-action="copy"]').onclick = () => copyWildcardRef(file);

        const fileInput = card.querySelector(".ap-preview-input");
        card.querySelector('[data-action="preview"]').onclick = () => fileInput.click();
        fileInput.onchange = () => uploadPreview(file, fileInput.files[0]);

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
    formData.append("folder", state.activeFolder);
    formData.append("path", file.relPath);
    formData.append("image", blob);

    try {
        const res = await fetch(`${API}/preview`, { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        log(`Preview updated for ${file.relPath}`);
        loadFiles();
    } catch (e) {
        log(`Preview upload failed: ${e.message}`, true);
    }
}

// ---------- editor ----------
async function openEditor(file) {
    try {
        const data = await apiGet(`/file?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(file.relPath)}&type=${file.type}`);
        state.activeFile = file;
        document.getElementById("ap-editor-filename").textContent = `${file.relPath}.${file.type}`;
        document.getElementById("ap-editor-textarea").value = data.content;
        // TODO: wire adaptive_highlighter.js / adaptive_theme.css in here for file.type === "txt".
        // file.type === "json" stays plain until the modular JSON editor exists.
        setEditorOpen(true);
    } catch (e) {
        log(`Failed to open ${file.relPath}: ${e.message}`, true);
    }
}

async function editorSave() {
    if (!state.activeFile) return;
    try {
        await apiSend("/file", {
            folder: state.activeFolder, path: state.activeFile.relPath,
            type: state.activeFile.type, content: document.getElementById("ap-editor-textarea").value,
        });
        log(`Saved ${state.activeFile.relPath}.${state.activeFile.type}`);
        flashSaved();
    } catch (e) {
        log(`Failed to save: ${e.message}`, true);
    }
}
document.getElementById("ap-editor-save").onclick = editorSave;

function flashSaved() {
    const panel = document.getElementById("ap-editor-panel");
    panel.classList.remove("ap-flash-save");
    void panel.offsetWidth; // restart the animation even on back-to-back saves
    panel.classList.add("ap-flash-save");
}

async function editorGenerate() {
    if (!state.activeFile) return;
    await editorSave(); // save first, so Quick Generate reflects the latest edits
    quickGenerate(state.activeFile.relPath);
}
document.getElementById("ap-editor-generate").onclick = editorGenerate;

// ---------- quick generate (shared by cards + editor) ----------
async function quickGenerate(relPath) {
    const seed = parseInt(document.getElementById("ap-seed-input").value, 10);
    try {
        const data = await apiSend("/generate", {
            folder: state.activeFolder, path: relPath,
            seed: Number.isFinite(seed) ? seed : -1,
        });
        log(`__${relPath}__ (seed ${data.seed}) → ${data.result}`);
    } catch (e) {
        log(`Generate failed for ${relPath}: ${e.message}`, true);
    }
}

// ---------- keybinds ----------
document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); editorSave(); }
    else if (mod && e.key === "Enter") { e.preventDefault(); editorGenerate(); }
});

// ---------- init ----------
loadFolderTree();
log("Wildcard Manager ready.");