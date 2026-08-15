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
let isResizing = false;

function setEditorOpen(open) {
    editorOpen = open;
    const panel = document.getElementById("ap-editor-panel");
    const resizer = document.getElementById("ap-resizer");

    if (open) {
        panel.classList.remove("collapsed");
        resizer.classList.remove("hidden");
        if (!panel.style.width) panel.style.width = "420px"; // Default width
    } else {
        panel.classList.add("collapsed");
        resizer.classList.add("hidden");
        panel.style.width = ""; // Let CSS handle 0
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

    // Bounds constraints
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
    row.onclick = () => {
        state.activeFolder = categoryLabel;
        state.currentPath = path;
        renderFolderTree();
        loadFiles();
    };

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
        card.querySelector('[data-action="edit"]').onclick = () => openEditor(file);
        card.querySelector('[data-action="generate"]').onclick = () => quickGenerate(file.relPath);
        card.querySelector('[data-action="copy"]').onclick = () => copyWildcardRef(file);

        const fileInput = card.querySelector(".ap-preview-input");
        card.querySelector('[data-action="preview"]').onclick = () => fileInput.click();
        fileInput.onchange = () => uploadPreview(file, fileInput.files[0]);

        // Change 4: Left-click and Right-click Card actions
        card.addEventListener('click', (e) => {
            // Prevent triggering if clicked on the toolbar buttons or hidden input
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

        const modeToggle = document.getElementById('ap-editor-mode-toggle');

        if (file.type === "json") {
            // Enable and show Builder UI for JSON
            modeToggle.classList.remove('hidden');
            JSONBuilder.open(data.content);
        } else {
            // Force raw view and hide toggle for TXT
            modeToggle.classList.add('hidden');
            JSONBuilder.close();

            // Explicitly ensure the container reverts to raw formatting
            document.getElementById('ap-editor-content-area').className = 'ap-content-raw';
        }

        setEditorOpen(true);
    } catch (e) {
        log(`Failed to open ${file.relPath}: ${e.message}`, true);
    }
}

async function editorSave() {
    if (!state.activeFile) return;

    const textarea = document.getElementById("ap-editor-textarea");

    // NEW: Rule Enforcement — If editing a JSON file in Raw or Hybrid mode,
    // trigger an update to the Builder view ONLY on save.
    if (state.activeFile.type === "json" && (JSONBuilder.mode === "raw" || JSONBuilder.mode === "hybrid")) {
        JSONBuilder.syncFromRaw(textarea.value);
    }

    try {
        await apiSend("/file", {
            folder: state.activeFolder,
            path: state.activeFile.relPath,
            type: state.activeFile.type,
            content: textarea.value,
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


// ---------- file context menu (card right click) ----------
function showFileContextMenu(e, file) {
    const menu = document.getElementById("ap-context-menu");
    menu.innerHTML = "";

    // Edit
    const editBtn = document.createElement("button");
    editBtn.innerHTML = "<i class='pi pi-pencil'></i> Edit";
    editBtn.onclick = () => { hideContextMenu(); openEditor(file); };
    menu.appendChild(editBtn);

    const divider = document.createElement("hr");
    divider.style.borderColor = "var(--ap-border)";
    divider.style.margin = "4px 0";
    menu.appendChild(divider);

    // Duplicate
    const dupBtn = document.createElement("button");
    dupBtn.innerHTML = "<i class='pi pi-copy'></i> Duplicate";
    dupBtn.onclick = async () => {
        hideContextMenu();
        try {
            const data = await apiGet(`/file?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(file.relPath)}&type=${file.type}`);

            // Auto-increment naming logic
            let newPath = file.relPath;
            const match = newPath.match(/_(\d+)$/);
            if (match) {
                newPath = newPath.substring(0, match.index) + '_' + (parseInt(match[1]) + 1);
            } else {
                newPath += "_1";
            }

            await apiSend("/file", {
                folder: state.activeFolder,
                path: newPath,
                type: file.type,
                content: data.content
            });
            log(`Duplicated file as ${newPath}`);
            loadFiles();
        } catch (err) { log(`Failed to duplicate: ${err.message}`, true); }
    };
    menu.appendChild(dupBtn);

    // Rename
    const renBtn = document.createElement("button");
    renBtn.innerHTML = "<i class='pi pi-file-edit'></i> Rename";
    renBtn.onclick = async () => {
        hideContextMenu();
        const newName = prompt("Enter new filename:", file.relPath);
        if (!newName || newName === file.relPath) return;
        try {
            // Read content -> Write to new path -> Delete old path
            const data = await apiGet(`/file?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(file.relPath)}&type=${file.type}`);
            await apiSend("/file", { folder: state.activeFolder, path: newName, type: file.type, content: data.content });
            await apiSend(`/file?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(file.relPath)}`, {}, "DELETE");

            log(`Renamed file to ${newName}`);
            loadFiles();
        } catch (err) { log(`Failed to rename: ${err.message}`, true); }
    };
    menu.appendChild(renBtn);

    // Delete
    const delBtn = document.createElement("button");
    delBtn.innerHTML = "<i class='pi pi-trash'></i> Delete";
    delBtn.style.color = "var(--ap-danger)";
    delBtn.onclick = async () => {
        hideContextMenu();
        if (!confirm(`Are you sure you want to delete ${file.relPath}.${file.type}?`)) return;
        try {
            await apiSend(`/file?folder=${encodeURIComponent(state.activeFolder)}&path=${encodeURIComponent(file.relPath)}`, {}, "DELETE");
            log(`Deleted ${file.relPath}`);

            if (state.activeFile && state.activeFile.relPath === file.relPath) setEditorOpen(false); // Close editor if deleted file was open
            loadFiles();
        } catch (err) { log(`Failed to delete: ${err.message}`, true); }
    };
    menu.appendChild(delBtn);

    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;
    menu.style.display = "block";
}


// ---------- top nav buttons ----------
// ---------- top nav buttons ----------
document.getElementById("ap-btn-refresh").onclick = () => {
    loadFolderTree();
    log("Refreshed wildcard structural data.");
};

document.getElementById("ap-btn-new-file").onclick = () => {
    if (!state.activeFolder) {
        alert("Please select a folder first.");
        return;
    }

    // Open the new custom modal, passing the current sub-directory path
    NewFileModal.open(state.currentPath || "");
};

const NewFileModal = {
    currentPath: '',
    // Load preference from memory, default to JSON
    selectedType: localStorage.getItem('ap_new_file_type') || 'json',

    init() {
        this.updateToggleUI();

        // Bind type toggles
        document.getElementById('ap-toggle-txt').onclick = () => this.setType('txt');
        document.getElementById('ap-toggle-json').onclick = () => this.setType('json');

        // Bind input events
        const input = document.getElementById('ap-new-file-input');
        input.oninput = () => this.updatePreview();
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.confirm();
            if (e.key === 'Escape') this.close();
        });

        // Bind core buttons
        document.getElementById('ap-new-file-cancel').onclick = () => this.close();
        document.getElementById('ap-new-file-backdrop').onclick = () => this.close();
        document.getElementById('ap-new-file-confirm').onclick = () => this.confirm();
    },

    open(folderPath) {
        this.currentPath = folderPath;
        const modal = document.getElementById('ap-new-file-modal');
        const input = document.getElementById('ap-new-file-input');

        input.value = '';
        this.updatePreview();
        modal.classList.remove('hidden');
        input.focus();
    },

    close() {
        document.getElementById('ap-new-file-modal').classList.add('hidden');
    },

    setType(type) {
        this.selectedType = type;
        localStorage.setItem('ap_new_file_type', type); // Save to memory
        this.updateToggleUI();
    },

    updateToggleUI() {
        const btnTxt = document.getElementById('ap-toggle-txt');
        const btnJson = document.getElementById('ap-toggle-json');

        if (this.selectedType === 'txt') {
            btnTxt.classList.add('active');
            btnJson.classList.remove('active');
        } else {
            btnTxt.classList.remove('active');
            btnJson.classList.add('active');
        }
    },

    updatePreview() {
        const inputVal = document.getElementById('ap-new-file-input').value.trim();
        const previewEl = document.getElementById('ap-new-file-preview');

        if (!inputVal) {
            previewEl.textContent = '';
            return;
        }

        // Clean up the path to match the Adaptive Prompts call syntax
        // Removes root '/wildcards/' or similar prefixes and trailing slashes
        let cleanPath = this.currentPath.replace(/^[\/\\]*(wildcards)?[\/\\]*/i, '');
        if (cleanPath && !cleanPath.endsWith('/')) {
            cleanPath += '/';
        }

        previewEl.textContent = `__${cleanPath}${inputVal}__`;
    },

    async confirm() {
        const filename = document.getElementById('ap-new-file-input').value.trim();
        if (!filename) return;

        // Ensure the user didn't accidentally type an extension
        const cleanFileName = filename.replace(/\.(json|txt)$/i, '');

        // Prevent leading slashes if currentPath is empty (root folder)
        const fullPath = this.currentPath
            ? `${this.currentPath}/${cleanFileName}`
            : cleanFileName;

        try {
            // Provide boilerplate default content if JSON is selected
            const initialContent = this.selectedType === 'json'
                ? '{\n    "variables": {},\n    "loras": [],\n    "generate": []\n}'
                : '';

            // Send to your correct existing backend endpoint
            await apiSend("/file", {
                folder: state.activeFolder,
                path: fullPath,
                type: this.selectedType,
                content: initialContent
            });

            log(`Created ${cleanFileName}.${this.selectedType}`);
            this.close();

            // Refresh the file grid to show the new item
            loadFiles();
        } catch (e) {
            log(`Failed to create file: ${e.message}`, true);
        }
    }
};

// Make sure to initialize it once the DOM loads
document.addEventListener('DOMContentLoaded', () => {
    NewFileModal.init();
});