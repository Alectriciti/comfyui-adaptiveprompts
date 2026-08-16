"""
Adaptive Prompts: Wildcard Manager
Backend routes for the standalone /adaptiveprompts page.
"""

import os
import random
import json
from aiohttp import web
from server import PromptServer
import subprocess
import sys

from .generator import evaluate_prompt_core, SeededRandom
from .wildcard_utils import build_category_options, clear_category_cache, _default_package_root

_WEB_DIR = os.path.join(_default_package_root(), "web", "wildcard_manager")

# Add this helper function near your other helpers:
_MANAGER_CONFIG_PATH = os.path.join(_default_package_root(), "config_wildcard_manager.json")

def _load_manager_config():
    if os.path.isfile(_MANAGER_CONFIG_PATH):
        try:
            with open(_MANAGER_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"card_aspect": "portrait"} # default

def _safe_join(base_dir: str, rel_path: str) -> str:
    """
    Joins rel_path onto base_dir and guarantees the result can't escape
    base_dir (blocks ../ traversal from API query/body params).
    """
    rel_path = (rel_path or "").strip().lstrip("/\\")
    full = os.path.normpath(os.path.join(base_dir, rel_path))
    base_real = os.path.realpath(base_dir)
    full_real = os.path.realpath(full)
    if not (full_real == base_real or full_real.startswith(base_real + os.sep)):
        raise ValueError(f"Path escapes base directory: {rel_path}")
    return full


def _resolve_folder(label: str) -> str:
    """Returns the absolute directory for a category label, or raises KeyError."""
    _, folder_map, _ = build_category_options()
    if label not in folder_map:
        raise KeyError(label)
    return folder_map[label]


# ---------- page + static assets ----------

@PromptServer.instance.routes.get("/adaptiveprompts")
async def wildcard_manager_page(request):
    return web.FileResponse(os.path.join(_WEB_DIR, "index.html"))

PromptServer.instance.routes.static("/adaptiveprompts/assets", _WEB_DIR)


# ---------- folders ----------

@PromptServer.instance.routes.get("/adaptiveprompts/api/folders")
async def list_folders(request):
    labels, _, tooltip = build_category_options()
    return web.json_response({"folders": [{"label": l} for l in labels], "tooltip": tooltip})

def _build_folder_tree(dir_path: str, max_depth: int = 8, _depth: int = 0):
    """Recursively lists subdirectories of dir_path as {"name", "children"} nodes."""
    if _depth >= max_depth or not os.path.isdir(dir_path):
        return []
    nodes = []
    try:
        entries = sorted(os.listdir(dir_path))
    except OSError:
        return []
    for entry in entries:
        full = os.path.join(dir_path, entry)
        if os.path.isdir(full):
            nodes.append({"name": entry, "children": _build_folder_tree(full, max_depth, _depth + 1)})
    return nodes


@PromptServer.instance.routes.get("/adaptiveprompts/api/folder-tree")
async def get_folder_tree(request):
    labels, folder_map, _ = build_category_options()
    tree = [{"label": label, "children": _build_folder_tree(folder_map[label])} for label in labels]
    return web.json_response({"tree": tree})

@PromptServer.instance.routes.post("/adaptiveprompts/api/folders")
async def create_folder(request):
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        if not name or not all(c.isalnum() or c in "_-" for c in name):
            return web.json_response({"error": "Folder name must be alphanumeric (with _ or -)"}, status=400)

        new_dir = os.path.join(_default_package_root(), f"wildcards_{name}")
        os.makedirs(new_dir, exist_ok=True)
        clear_category_cache()
        return web.json_response({"status": "success", "folder": f"wildcards_{name}"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.delete("/adaptiveprompts/api/folders/{folder}")
async def delete_folder(request):
    label = request.match_info["folder"]
    if label == "wildcards":
        return web.json_response({"error": "The default 'wildcards' folder can't be deleted"}, status=400)
    try:
        target = _resolve_folder(label)
    except KeyError:
        return web.json_response({"error": f"Unknown folder '{label}'"}, status=404)

    try:
        if os.listdir(target):
            return web.json_response({"error": "Folder is not empty"}, status=400)
        os.rmdir(target)
        clear_category_cache()
        return web.json_response({"status": "success"})
    except OSError as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------- files ----------

@PromptServer.instance.routes.get("/adaptiveprompts/api/files")
async def list_files(request):
    label = request.query.get("folder", "")
    sub_path = request.query.get("path", "")

    try:
        base_dir = _resolve_folder(label)
        target_dir = _safe_join(base_dir, sub_path)
    except KeyError:
        return web.json_response({"error": f"Unknown folder '{label}'"}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    if not os.path.isdir(target_dir):
        return web.json_response({"error": "Not a directory"}, status=404)

    subfolders, files = [], []
    for entry in sorted(os.listdir(target_dir)):
        full = os.path.join(target_dir, entry)
        if os.path.isdir(full):
            subfolders.append(entry)
            continue
        name, ext = os.path.splitext(entry)
        if ext.lower() not in (".txt", ".json"):
            continue
        rel_name = f"{sub_path}/{name}".strip("/") if sub_path else name
        files.append({
            "name": name,
            "relPath": rel_name,
            "type": ext.lower().lstrip("."),
            "hasPreview": os.path.isfile(os.path.join(target_dir, f"{name}.png")),
        })

    return web.json_response({"folder": label, "path": sub_path, "subfolders": subfolders, "files": files})


@PromptServer.instance.routes.get("/adaptiveprompts/api/file")
async def get_file(request):
    label = request.query.get("folder", "")
    rel_path = request.query.get("path", "")
    file_type = request.query.get("type", "txt")

    try:
        base_dir = _resolve_folder(label)
        full = _safe_join(base_dir, f"{rel_path}.{file_type}")
    except KeyError:
        return web.json_response({"error": f"Unknown folder '{label}'"}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    if not os.path.isfile(full):
        return web.json_response({"error": "File not found"}, status=404)

    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    return web.json_response({"content": content})


@PromptServer.instance.routes.post("/adaptiveprompts/api/file")
async def save_file(request):
    try:
        data = await request.json()
        base_dir = _resolve_folder(data["folder"])
        full = _safe_join(base_dir, f"{data['path']}.{data.get('type', 'txt')}")

        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(data.get("content", ""))
        return web.json_response({"status": "success"})
    except KeyError as e:
        return web.json_response({"error": f"Missing/unknown field: {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.get("/adaptiveprompts/api/preview")
async def get_preview(request):
    label = request.query.get("folder", "")
    rel_path = request.query.get("path", "")
    try:
        base_dir = _resolve_folder(label)
        full = _safe_join(base_dir, f"{rel_path}.png")
    except (KeyError, ValueError):
        return web.Response(status=404)

    if not os.path.isfile(full):
        return web.Response(status=404)
    return web.FileResponse(full)

@PromptServer.instance.routes.post("/adaptiveprompts/api/preview")
async def upload_preview(request):
    try:
        reader = await request.multipart()
        folder = rel_path = None
        image_bytes = None

        async for field in reader:
            if field.name == "folder":
                folder = (await field.read()).decode("utf-8")
            elif field.name == "path":
                rel_path = (await field.read()).decode("utf-8")
            elif field.name == "image":
                image_bytes = await field.read()

        if not folder or not rel_path or image_bytes is None:
            return web.json_response({"error": "Missing folder, path, or image"}, status=400)

        base_dir = _resolve_folder(folder)
        full = _safe_join(base_dir, f"{rel_path}.png")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(image_bytes)

        return web.json_response({"status": "success"})
    except KeyError:
        return web.json_response({"error": "Unknown folder"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------- quick generate ----------

@PromptServer.instance.routes.post("/adaptiveprompts/api/generate")
async def quick_generate(request):
    try:
        data = await request.json()
        base_dir = _resolve_folder(data["folder"])
        rel_path = data["path"]

        try:
            requested_seed = int(data.get("seed", -1))
        except (TypeError, ValueError):
            requested_seed = -1
        seed = random.getrandbits(32) if requested_seed < 0 else requested_seed

        rng = SeededRandom(seed)
        result = evaluate_prompt_core(f"__{rel_path}__", rng, base_dir, resolved_vars={}, hide_comments=True)
        return web.json_response({"result": result, "seed": seed})
    except KeyError as e:
        return web.json_response({"error": f"Missing/unknown field: {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

try:
    from send2trash import send2trash as _send_to_trash
    _HAS_TRASH = True
except ImportError:
    _HAS_TRASH = False


@PromptServer.instance.routes.delete("/adaptiveprompts/api/file")
async def delete_file(request):
    label = request.query.get("folder", "")
    rel_path = request.query.get("path", "")
    file_type = request.query.get("type", "")

    try:
        base_dir = _resolve_folder(label)
    except KeyError:
        return web.json_response({"error": f"Unknown folder '{label}'"}, status=404)

    # type isn't always known by the caller -- try both extensions if omitted.
    target = None
    for ext in ([file_type] if file_type else ["txt", "json"]):
        try:
            full = _safe_join(base_dir, f"{rel_path}.{ext}")
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        if os.path.isfile(full):
            target = full
            break

    if target is None:
        return web.json_response({"error": "File not found"}, status=404)

    try:
        if _HAS_TRASH:
            _send_to_trash(target)
            method = "recycle bin"
        else:
            os.remove(target)
            method = "permanently deleted (install send2trash for recycle-bin support)"
        return web.json_response({"status": "success", "method": method})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

def _folder_dir_for(label: str, sub_path: str) -> str:
    return _safe_join(_resolve_folder(label), sub_path)


@PromptServer.instance.routes.post("/adaptiveprompts/api/folder/create-sub")
async def create_subfolder(request):
    try:
        data = await request.json()
        label = data["folder"]
        sub_path = data.get("path", "")
        name = (data.get("name") or "").strip()

        if not name or not all(c.isalnum() or c in "_- " for c in name):
            return web.json_response({"error": "Invalid folder name"}, status=400)

        parent_dir = _folder_dir_for(label, sub_path)
        new_dir = os.path.join(parent_dir, name)
        if os.path.exists(new_dir):
            return web.json_response({"error": "A folder with that name already exists"}, status=400)

        os.makedirs(new_dir)
        clear_category_cache()
        return web.json_response({"status": "success"})
    except KeyError:
        return web.json_response({"error": "Unknown folder"}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.post("/adaptiveprompts/api/folder/rename")
async def rename_folder(request):
    try:
        data = await request.json()
        label = data["folder"]
        sub_path = data.get("path", "")
        new_name = (data.get("newName") or "").strip()

        if not new_name:
            return web.json_response({"error": "New name can't be empty"}, status=400)

        if sub_path == "":
            if label == "wildcards":
                return web.json_response({"error": "The default 'wildcards' folder can't be renamed"}, status=400)
            if not new_name.startswith("wildcards_"):
                new_name = f"wildcards_{new_name}"
            old_dir = _resolve_folder(label)
            new_dir = os.path.join(_default_package_root(), new_name)
        else:
            if not all(c.isalnum() or c in "_- " for c in new_name):
                return web.json_response({"error": "Invalid folder name"}, status=400)
            old_dir = _folder_dir_for(label, sub_path)
            new_dir = os.path.join(os.path.dirname(old_dir), new_name)

        if os.path.exists(new_dir):
            return web.json_response({"error": "A folder with that name already exists"}, status=400)

        os.rename(old_dir, new_dir)
        clear_category_cache()
        return web.json_response({"status": "success"})
    except KeyError:
        return web.json_response({"error": "Unknown folder"}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)



def reveal_in_os(path: str):
    """Cross-platform function to reveal a file or folder in the native OS file explorer."""
    try:
        if sys.platform == "win32":
            # Windows: Opens Explorer with the item selected
            subprocess.run(['explorer', '/select,', os.path.normpath(path)])
        elif sys.platform == "darwin":
            # macOS: Opens Finder with the item selected
            subprocess.run(['open', '-R', path])
        else:
            # Linux/Unix: Falls back to opening the parent directory
            target = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.run(['xdg-open', target])
    except Exception as e:
        print(f"Failed to reveal in OS: {e}")

@PromptServer.instance.routes.post("/adaptiveprompts/api/reveal")
async def reveal_item(request):
    try:
        data = await request.json()
        label = data["folder"]
        sub_path = data.get("path", "")
        file_type = data.get("type", "")

        base_dir = _resolve_folder(label)

        if file_type:
            # It's a file
            full_path = _safe_join(base_dir, f"{sub_path}.{file_type}")
        else:
            # It's a folder
            if sub_path == "":
                full_path = base_dir
            else:
                full_path = _folder_dir_for(label, sub_path)

        if not os.path.exists(full_path):
            return web.json_response({"error": "Path not found"}, status=404)

        reveal_in_os(full_path)
        return web.json_response({"status": "success"})
    except KeyError as e:
        return web.json_response({"error": f"Missing/unknown field: {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


    
@PromptServer.instance.routes.get("/adaptiveprompts/api/config")
async def get_manager_config(request):
    return web.json_response(_load_manager_config())

@PromptServer.instance.routes.post("/adaptiveprompts/api/config")
async def save_manager_config(request):
    try:
        data = await request.json()
        config = _load_manager_config()
        config.update(data)
        with open(_MANAGER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)