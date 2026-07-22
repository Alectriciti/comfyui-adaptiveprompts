# wildcard_utils.py
import os
import functools
import collections
from .config import get_config


# ---------- helpers for normalizing contexts ----------
def _ensure_bucket_dict(bucket_like):
    """
    Convert incoming bucket to canonical dict(origin->value).
    Accepts:
        - dict: assumed origin->value mapping -> returned as-is (copy)
        - list/tuple: converted to { "__combined_0": v0, "__combined_1": v1, ... }
        - single value: converted to { "__combined_0": value }
    """
    if bucket_like is None:
        return {}
    if isinstance(bucket_like, dict):
        # copy and stringify values
        out = {}
        for k, v in bucket_like.items():
            out[str(k)] = str(v)
        return out
    if isinstance(bucket_like, (list, tuple, set)):
        out = {}
        i = 0
        for v in bucket_like:
            out[f"__combined_{i}"] = str(v)
            i += 1
        return out
    # single scalar
    return {"__combined_0": str(bucket_like)}

def _normalize_input_context(ctx):
    """
    Convert arbitrary incoming context into dict[var_name] -> dict[origin->value].
    """
    if not ctx:
        return {}
    normalized = {}
    for var, bucket in ctx.items():
        normalized[var] = _ensure_bucket_dict(bucket)
    return normalized

def _snapshot_context(context: dict) -> dict:
    """
    Creates a snapshot of the current keys in the context.
    Used in conjunction with `_apply_context_override` to support "override" logic.
    """
    snapshot = {}
    for k, v in context.items():
        if isinstance(v, dict):
            snapshot[k] = list(v.keys())
    return snapshot

def _apply_context_override(context: dict, snapshot: dict) -> None:
    """
    Compares the current context against a snapshot. If a variable had new origins added
    since the snapshot, the old origins are deleted, effectively "overriding" the old values.
    Modifies the context in-place.
    """
    for k, old_keys in snapshot.items():
        if k in context and isinstance(context[k], dict):
            current_keys = list(context[k].keys())
            new_keys = [key for key in current_keys if key not in old_keys]
            if new_keys:
                for old_k in old_keys:
                    del context[k][old_k]


def _default_package_root():
    # package root is one directory above the module file
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

@functools.lru_cache(maxsize=4)
def build_category_options(base_dir: str | None = None):
    """
    Discover folders beginning with 'wildcards' inside the configured base directories.

    When base_dir is None (default), scans all configured wildcard directories in order:
      1. Custom wildcard directory (from settings, if defined and exists)
      2. Package root (built-in wildcards)

    When base_dir is explicitly provided, only scans that single directory.

    Returns: (labels_list, label_to_folder_map, tooltip_str)

    - Labels are deduplicated; first occurrence wins (custom takes priority over built-in)
    - Always ensures at least 'wildcards' exists as a fallback
    """
    if base_dir is not None:
        # Explicit base_dir — only scan that directory
        label_list, label_to_folder = _scan_single_base(base_dir)
    else:
        # Scan all configured base directories
        base_dirs = []
        custom_dir = get_config("custom_wildcard_dir")
        if custom_dir and os.path.isdir(custom_dir):
            base_dirs.append(custom_dir)
        base_dirs.append(_default_package_root())

        label_list = []
        label_to_folder = {}

        for bd in base_dirs:
            for fname in _get_wildcard_folders(bd):
                if fname not in label_to_folder:
                    label_list.append(fname)
                    # map label to absolute folder path under base_dir
                    label_to_folder[fname] = os.path.join(bd, fname)

        # Ensure 'wildcards' fallback exists
        if "wildcards" not in label_to_folder:
            label_list.insert(0, "wildcards")
            label_to_folder["wildcards"] = os.path.join(_default_package_root(), "wildcards")

    tooltip = (
        "Select which wildcards folder to use. Create alternate folders named "
        "'wildcards_*' (eg. 'wildcards_fresh') inside the package root or a "
        "custom directory configured in settings.\n\n"
        "defaults to the global '/wildcards/' if a file is missing"
    )

    return label_list, label_to_folder, tooltip


def _get_wildcard_folders(base_dir: str) -> list[str]:
    """Return sorted list of directory names starting with 'wildcard' inside base_dir."""
    try:
        result = []
        for name in os.listdir(base_dir):
            path = os.path.join(base_dir, name)
            if os.path.isdir(path) and name.startswith("wildcard"):
                result.append(name)
        return sorted(result)
    except Exception:
        return []


def _scan_single_base(base_dir: str) -> tuple[list[str], dict[str, str]]:
    """Scan a single base directory for wildcard folders (legacy path)."""
    folder_names = _get_wildcard_folders(base_dir)

    if "wildcards" not in folder_names:
        folder_names.insert(0, "wildcards")

    label_list = []
    label_to_folder = {}
    for fname in folder_names:
        label_list.append(fname)
        label_to_folder[fname] = os.path.join(base_dir, fname)

    return label_list, label_to_folder

def clear_category_cache():
    """
    Clear the cached results (useful if you add/remove wildcard folders at runtime
    and need the dropdowns to refresh).
    """
    build_category_options.cache_clear()


def bfs_find_file(search_root: str, target_name: str) -> str | None:
    """
    Searches downwards from search_root using Breadth-First Search.
    Finds the first occurrence of '{target_name}.txt'. 
    Does not support globs (*) to avoid ambiguous tree resolution.
    """
    if not search_root or not os.path.isdir(search_root):
        return None
        
    if "*" in target_name:
        return None # BFS with globs is ambiguous and disabled

    target_file = f"{target_name}.txt"
    queue = collections.deque([search_root])
    visited = set()

    while queue:
        current = queue.popleft()
        try:
            current_real = os.path.realpath(current)
        except OSError:
            continue
            
        if current_real in visited:
            continue
        visited.add(current_real)

        candidate = os.path.join(current, target_file)
        if os.path.isfile(candidate):
            return candidate

        try:
            entries = sorted(os.listdir(current))
        except OSError:
            continue
            
        for entry in entries:
            full = os.path.join(current, entry)
            if os.path.isdir(full):
                queue.append(full)
                
    return None
