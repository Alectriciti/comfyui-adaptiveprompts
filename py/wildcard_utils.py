# wildcard_utils.py
import os
import json
import functools
import collections


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
    Discover folders beginning with 'wildcards' inside 'base_dir' (defaults to package root).
    Returns: (labels_list, label_to_folder_map, tooltip_str)

    - 'wildcards' -> label 'Default'
    - 'wildcards_foo' -> label 'FOO' (suffix uppercased)
    - Always ensures at least 'wildcards' exists (fallback)
    """
    if base_dir is None:
        base_dir = _default_package_root()

    folder_names = []
    try:
        for name in os.listdir(base_dir):
            path = os.path.join(base_dir, name)
            if os.path.isdir(path) and name.startswith("wildcard"):
                folder_names.append(name)
    except Exception:
        folder_names = []

    # Ensure 'wildcards' fallback exists in the list (so user always has at least Default)
    if "wildcards" not in folder_names:
        # prefer to put real existing 'wildcards' first if present else ensure at least label
        folder_names.insert(0, "wildcards")

    label_list = []
    label_to_folder = {}
    for fname in folder_names:
        label = fname
        label_list.append(label)
        # map label to absolute folder path under base_dir
        label_to_folder[label] = os.path.join(base_dir, fname)

    tooltip = (
        "Select which wildcards folder to use. Create alternate folders named "
        "'wildcards_*' (eg. 'wildcards_fresh') inside the package root.\n\n"
        "defaults to the global '/wildcards/ if a file is missing'"
    )

    return label_list, label_to_folder, tooltip

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

    # .json takes precedence over .txt when a directory has both.
    target_files = (f"{target_name}.json", f"{target_name}.txt")
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

        for target_file in target_files:
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

# ---------- JSON wildcard files (.json) ----------

def _load_json_file(filepath: str):
    """
    Shared raw JSON loader for both plain .json wildcard files and the JSON
    Payload Engine below. Returns the parsed JSON, or None on any read/parse
    failure (logged, not raised -- one bad wildcard file shouldn't take down
    a whole prompt evaluation).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[Adaptive Prompts] Failed to load JSON file '{filepath}': {e}")
        return None


def load_json_wildcard_file(filepath: str):
    """
    Loads a single .json wildcard file -- the .json counterpart to a plain
    .txt wildcard file -- and returns (items, weights) in EXACTLY the shape
    _load_weighted_file() returns for .txt.

    Accepted top-level JSON shapes:
        ["red%3%", "green%2%", "blue"]
        {"choices": ["red%3%", "green%2%", "blue"]}
    """
    from .generator import _parse_weighted_options  # deferred: see note above

    data = _load_json_file(filepath)
    if isinstance(data, list):
        choices = data
    elif isinstance(data, dict):
        choices = data.get("choices", [])
    else:
        choices = []

    return _parse_weighted_options(str(c) for c in choices)



# ---------- JSON Payload Engine (variables / loras / generate) — v0.1 ----------

def load_json_payload_file(filepath: str) -> dict:
    """Convenience loader for a JSON Payload Engine file on disk."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_variable_definition(var_name: str,
                                  definition,
                                  var_rng,
                                  wildcard_dir: str,
                                  resolved_vars: dict) -> None:
    """
    Pre-populates resolved_vars[var_name] from ONE entry of a payload's
    "variables" object. Mutates resolved_vars in place.

    This is the JSON equivalent of the manual {a|b|c}^x^y^z chain-assignment
    syntax -- it just runs from data instead of from prompt text.

    `definition` shapes:
      - a plain string/scalar:
            resolved once through resolve_wildcards() and stored as the
            variable's single entry. eg "age": "{30|35|40}"

      - {"quantity": <expr>, "choices": [...]}:
            "quantity" accepts anything a bracket count does -- a plain int
            ("5"), a range ("3-8"), "*" (meaning "one of every choice"), or a
            bracket/wildcard expression that resolves to one of those
            ("{1|2|3|4|5|__number__}"). That many DISTINCT choices (no
            repeats until the pool is exhausted, then it wraps) are drawn
            from "choices" -- same %weight% + nested bracket/wildcard syntax
            as a .txt wildcard file -- and each is resolved and stored as
            its own entry, exactly like repeated ^x^y^z picks.
    """
    from .generator import (
        resolve_wildcards, _parse_weighted_options,
        _resolve_count_expression, _ensure_var_bucket, _deck_draw,
    )

    _ensure_var_bucket(resolved_vars, var_name)
    bucket = resolved_vars[var_name]

    def _store(value: str):
        bucket[f"__json_{len(bucket)}"] = value

    if isinstance(definition, dict):
        raw_choices = definition.get("choices", [])
        quantity_expr = str(definition.get("quantity", "1"))

        items, weights = _parse_weighted_options(str(c) for c in raw_choices)
        if not items:
            return

        quantity, exhaust_all = _resolve_count_expression(
            quantity_expr, var_rng, wildcard_dir,
            source_file=None, _resolved_vars=resolved_vars,
            bracket_ctx=None, bracket_overflow=True
        )
        quantity = len(items) if exhaust_all else max(1, quantity)

        # Ad-hoc deck: same no-repeat-until-exhausted draw logic used for
        # {N$$...} bracket choices, just seeded from an in-memory list
        # instead of a wildcard file.
        deck = {
            "all_items": list(items), "all_weights": list(weights),
            "remain_items": list(items), "remain_weights": list(weights),
        }
        for _ in range(quantity):
            picked = _deck_draw(deck, var_rng.next_rng(), allow_overflow=True)
            if picked is None:
                break
            resolved = resolve_wildcards(
                picked, var_rng, wildcard_dir,
                _resolved_vars=resolved_vars,
                bracket_ctx=None, bracket_overflow=True
            )
            _store(resolved)
    else:
        resolved = resolve_wildcards(
            str(definition), var_rng, wildcard_dir,
            _resolved_vars=resolved_vars,
            bracket_ctx=None, bracket_overflow=True
        )
        _store(resolved)


def evaluate_json_payload(payload: dict | str,
                           base_seed: int,
                           wildcard_dir: str,
                           rng_mode: str | None = None) -> dict:
    """
    Top-level entry point for the JSON Payload Engine (v0.1).

    `payload` may be an already-parsed dict, or a raw JSON string (a
    malformed string will raise json.JSONDecodeError -- deliberately not
    caught here, since this is the primary input and a silent empty result
    would be more confusing than a clear error).

    Runs the three phases in order, sharing one _resolved_vars context and
    one continuously-advancing SeededRandom across all of them, so __^name__
    style recalls stay consistent across every "generate" entry:
        1. variables -> pre-populates _resolved_vars (see _resolve_variable_definition)
        2. loras     -> resolved in turn; empty results (eg "{...|}" landing on
                        the empty branch) are dropped, non-empty ones space-joined
        3. generate  -> each template run through evaluate_prompt_core()

    Returns:
        {
          "prompts": [str, ...],           one resolved string per "generate" entry
          "lora_string": str,               non-empty resolved loras, space-joined
          "prompts_with_loras": [str, ...], each prompt with lora_string appended
          "context": dict,                  final _resolved_vars, for chaining into
                                             another node's context input
        }
    """
    from .generator import SeededRandom, resolve_wildcards, evaluate_prompt_core

    if isinstance(payload, str):
        payload = json.loads(payload)

    rng = SeededRandom(base_seed, mode=rng_mode)  # rng_mode=None -> config default ("Adaptive")
    resolved_vars: dict = {}

    # 1. variables -- each gets its own RNG branch so re-ordering or adding
    #    entries in the JSON doesn't cascade-shift another variable's random
    #    result. Same stability guarantee "Adaptive" mode gives everywhere else.
    for var_name, definition in (payload.get("variables") or {}).items():
        var_rng = rng.branch(f"json_var_{var_name}")
        _resolve_variable_definition(var_name, definition, var_rng, wildcard_dir, resolved_vars)

    # 2. loras
    lora_parts = []
    for lora_tpl in (payload.get("loras") or []):
        resolved = resolve_wildcards(
            str(lora_tpl), rng, wildcard_dir,
            _resolved_vars=resolved_vars,
            bracket_ctx=None, bracket_overflow=True
        ).strip()
        if resolved:
            lora_parts.append(resolved)
    lora_string = " ".join(lora_parts)

    # 3. generate
    prompts = []
    for template in (payload.get("generate") or []):
        prompts.append(
            evaluate_prompt_core(
                str(template), rng, wildcard_dir,
                resolved_vars=resolved_vars, hide_comments=True
            )
        )

    prompts_with_loras = [f"{p} {lora_string}" if lora_string else p for p in prompts]

    return {
        "prompts": prompts,
        "lora_string": lora_string,
        "prompts_with_loras": prompts_with_loras,
        "context": resolved_vars,
    }