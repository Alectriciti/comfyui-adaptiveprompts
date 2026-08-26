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

# --------- SPLIT -----------

def _normalize_choice_list(choices: list) -> list[str]:
    """
    Converts a mixed list of strings and {"output": "...", "chance": #} dicts
    into the standard %weight% formatted strings expected by the engine.
    """
    processed = []
    for c in choices:
        if isinstance(c, dict):
            out_str = str(c.get("output", ""))
            # Check for 'chance' or 'weight' for maximum flexibility
            chance = c.get("chance", c.get("weight"))
            if chance is not None:
                processed.append(f"{out_str}%{chance}%")
            else:
                processed.append(out_str)
        else:
            processed.append(str(c))
    return processed

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

    return _parse_weighted_options(_normalize_choice_list(choices))



# ---------- JSON Payload Engine (variables / loras / generate) — v0.1 ----------

def load_json_payload_file(filepath: str) -> dict:
    """Convenience loader for a JSON Payload Engine file on disk."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def _build_choice_pool(raw_choices: list, resolved_vars: dict):
    """
    Normalizes a raw choices/generate array -- a mix of plain strings and/or
    {"output", "chance"/"weight", "if", "set"} objects -- into a weighted pool
    ready for _parse_weighted_options(), after dropping any entry whose "if"
    condition fails against resolved_vars's CURRENT state.

    Shared by a variable's "choices" list AND a "generate" list, since a
    "generate" entry is exactly one of these same choice objects now --
    Adaptive Prompts just always draws exactly one from "generate" (no
    surrounding "quantity"), since resolving a wildcard call can only ever
    produce one string.

    Returns (items, weights, choice_metadata) where choice_metadata maps the
    internal uid-tagged string (still embedded in `items`) to that choice's
    raw "set" data -- see _extract_and_apply_picked.
    """
    from .generator import _parse_weighted_options

    valid_choices = []
    choice_metadata = {}

    for i, c in enumerate(raw_choices):
        if isinstance(c, dict):
            cond = c.get("if")
            if cond and not _evaluate_condition(cond, resolved_vars):
                continue  # condition failed -- not in the pool at all

            out_str = str(c.get("output", ""))
            chance = c.get("chance", c.get("weight"))

            # Unique id tag so "set" commands survive the %weight% string parser.
            uid_str = f"__uid_{i}__:{out_str}"

            if chance is not None:
                valid_choices.append(f"{uid_str}%{chance}%")
            else:
                valid_choices.append(uid_str)

            if "set" in c:
                choice_metadata[uid_str] = c["set"]
        else:
            valid_choices.append(str(c))

    items, weights = _parse_weighted_options(valid_choices)
    return items, weights, choice_metadata


def _extract_and_apply_picked(picked: str, choice_metadata: dict, resolved_vars: dict) -> str:
    """
    Given one item drawn from a _build_choice_pool() result, strips the
    internal uid tag back off, applies that choice's "set" commands (if any)
    to resolved_vars, and returns the clean output text -- still unresolved,
    ready for resolve_wildcards()/evaluate_prompt_core().
    """
    if picked.startswith("__uid_"):
        uid_parts = picked.split(":", 1)
        if len(uid_parts) == 2:
            uid_key = f"{uid_parts[0]}:{uid_parts[1]}"
            if uid_key in choice_metadata:
                _apply_set_commands(choice_metadata[uid_key], resolved_vars)
            picked = uid_parts[1]
    return picked

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

    _ensure_bucket = resolved_vars.get(var_name)

    if not isinstance(_ensure_bucket, dict):
        resolved_vars[var_name] = {}
        
    bucket = resolved_vars[var_name]

    def _store(value: str):
        # Find the next available JSON-specific origin index.
        json_index = 0
        while f"__json_{json_index}" in bucket:
            json_index += 1

        bucket[f"__json_{json_index}"] = value

    if isinstance(definition, list):
        definition = {"choices": definition}

    if isinstance(definition, dict):
        raw_choices = definition.get("choices", [])
        quantity_expr = str(definition.get("quantity", "1"))

        # --- 1. EVALUATE CONDITIONS AND BIND METADATA ---
        items, weights, choice_metadata = _build_choice_pool(raw_choices, resolved_vars)
        if not items:
            return

        quantity, exhaust_all = _resolve_count_expression(
            quantity_expr, var_rng, wildcard_dir,
            source_file=None, _resolved_vars=resolved_vars,
            bracket_ctx=None, bracket_overflow=True
        )
        quantity = len(items) if exhaust_all else max(1, quantity)

        deck = {
            "all_items": list(items), "all_weights": list(weights),
            "remain_items": list(items), "remain_weights": list(weights),
        }
        for _ in range(quantity):
                picked = _deck_draw(deck, var_rng.next_rng(), allow_overflow=True)
                if picked is None:
                    break

                picked = _extract_and_apply_picked(picked, choice_metadata, resolved_vars)

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

def _evaluate_condition(cond_expr: str, resolved_vars: dict) -> bool:
    """Evaluates lightweight logic: 'flag', 'key == val', 'key != val', '&&', '||'."""
    if not cond_expr:
        return True
        
    # Split into OR groups first
    for or_group in cond_expr.split("||"):
        all_and_true = True
        
        # Split into AND conditions within the OR group
        for cond in or_group.split("&&"):
            cond = cond.strip()
            if not cond:
                continue
                
            if "==" in cond:
                k, v = [x.strip() for x in cond.split("==", 1)]
                if k not in resolved_vars or v not in resolved_vars[k].values():
                    all_and_true = False
                    break
            elif "!=" in cond:
                k, v = [x.strip() for x in cond.split("!=", 1)]
                if k in resolved_vars and v in resolved_vars[k].values():
                    all_and_true = False
                    break
            else:
                # Existence check (flag)
                if cond not in resolved_vars:
                    all_and_true = False
                    break
                    
        if all_and_true:
            return True # Short-circuit OR success
            
    return False

def _apply_set_commands(set_data, resolved_vars: dict) -> None:
    """Applies overrides or empty flags to the context."""
    if not set_data:
        return
        
    # Handle Array format (can be string flags OR dictionaries)
    if isinstance(set_data, list):
        for item in set_data:
            if isinstance(item, dict):
                # If it's a dict inside a list, recursively process it
                _apply_set_commands(item, resolved_vars)
            else:
                # Treat as an empty flag
                flag_str = str(item)
                resolved_vars[flag_str] = {"__set": ""} 
            
    # Handle Dictionary format
    elif isinstance(set_data, dict):
        for k, v in set_data.items():
            k_str = str(k)
            
            # Handle an array of multiple values for a single variable
            if isinstance(v, list):
                # Clear the bucket and populate it with multiple indexed values
                resolved_vars[k_str] = {}
                for i, val in enumerate(v):
                    resolved_vars[k_str][f"__set_{i}"] = str(val)
            else:
                # Handle a single scalar value
                resolved_vars[k_str] = {"__set": str(v)}


def pick_generate_entry(raw_generate: list, rng, wildcard_dir: str, resolved_vars: dict) -> str:
    """
    Weighted-picks ONE entry from a "generate" array and returns its raw
    (still-unresolved) output text, applying that entry's "set" commands as
    a side effect on resolved_vars first.

    `rng` is a plain random.Random (matching _weighted_index), not a
    SeededRandom -- pass rng.next_rng() from your SeededRandom.

    Returns "" if nothing in the pool survives its "if" condition.
    """
    from .generator import _weighted_index

    items, weights, choice_metadata = _build_choice_pool(raw_generate, resolved_vars)
    if not items:
        return ""

    idx = _weighted_index(weights, rng)
    return _extract_and_apply_picked(items[idx], choice_metadata, resolved_vars)

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

    # 3. generate -- batch mode: every entry whose "if" condition passes
    # produces its own prompt (unlike pick_generate_entry's single weighted
    # pick, used for __name__-style wildcard calls). "chance" is intentionally
    # not used as an inclusion probability here.
    prompts = []
    for template in (payload.get("generate") or []):
        if isinstance(template, dict):
            cond = template.get("if")
            if cond and not _evaluate_condition(cond, resolved_vars):
                continue
            if "set" in template:
                _apply_set_commands(template["set"], resolved_vars)
            template = template.get("output", "")

        prompts.append(
            evaluate_prompt_core(
                str(template), rng, wildcard_dir,
                resolved_vars=resolved_vars, hide_comments=True
            )
        )

    prompts_with_loras = [f"{p}{lora_string}" if lora_string else p for p in prompts]

    return {
        "prompts": prompts,
        "lora_string": lora_string,
        "prompts_with_loras": prompts_with_loras,
        "context": resolved_vars,
    }

def bfs_find_file(search_root: str, target_name: str, validator=None) -> str | None:
    """
    Searches downwards from search_root using Breadth-First Search.
    Finds the first occurrence of '{target_name}.txt' or '{target_name}.json'. 
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
