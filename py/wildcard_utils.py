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
    from .generator import _parse_weighted_options

    valid_choices = []
    choice_metadata = {}
    choice_outputs = {}

    for i, c in enumerate(raw_choices):
        try:
            if isinstance(c, dict):
                cond = c.get("if")
                if cond and not _evaluate_condition(cond, resolved_vars):
                    continue  # condition failed -- not in the pool at all

                out_str = str(c.get("output", ""))
                chance = c.get("chance", c.get("weight"))
                uid_str = f"__uid_{i}__"

                choice_outputs[uid_str] = out_str

                if chance is not None:
                    valid_choices.append(f"{uid_str}%{chance}%")
                else:
                    valid_choices.append(uid_str)

                if "set" in c:
                    choice_metadata[uid_str] = c["set"]
            else:
                valid_choices.append(str(c))
        except Exception as e:
            print(f"[Adaptive Prompts] Skipping invalid choice in pool: {e}")
            continue

    items, weights = _parse_weighted_options(valid_choices)
    return items, weights, choice_metadata, choice_outputs


def _extract_and_apply_picked(
    picked: str,
    choice_metadata: dict,
    choice_outputs: dict,
    resolved_vars: dict,
    rng=None
) -> str:
    """
    Given one item drawn from a JSON choice pool:

      1. if it's a dict-choice's uid, recovers its actual output text and
         applies any `set` commands,
      2. if an RNG is supplied, performs the second-stage multiline weighted
         selection on the resulting output (a .txt-wildcard-style pick among
         its lines).

    Stages:  JSON `chance` -> selected choice -> output lines / `%weight%`
    """
    if picked in choice_outputs:
        if picked in choice_metadata:
            _apply_set_commands(choice_metadata[picked], resolved_vars)
        picked = choice_outputs[picked]
    # else: bare-string choice -- `picked` (already %weight%-stripped by the
    # first-stage parse) IS the output text, nothing further to look up.

    if rng is not None:
        picked = _select_json_output_line(picked, rng)

    return picked


def _select_json_output_line(output: str, rng) -> str:
    """
    Treat a JSON choice's output as a miniature TXT wildcard.

    Example:

        red%7
        green
        blue
        yellow

    becomes a weighted pool:

        red    -> 7
        green  -> 1
        blue   -> 1
        yellow -> 1

    The returned line has its inline %weight marker removed.
    """
    if output is None:
        return ""

    output = str(output)

    # splitlines() handles \n, \r\n, and \r.
    lines = output.splitlines()

    # Preserve a single-line output as a valid one-item pool.
    if not lines:
        lines = [output]

    from .generator import _parse_weighted_options, _weighted_index

    items, weights = _parse_weighted_options(lines)

    if not items:
        return ""

    idx = _weighted_index(weights, rng)
    return items[idx]

def _resolve_variable_definition(var_name: str,
                                  definition,
                                  var_rng,
                                  wildcard_dir: str,
                                  resolved_vars: dict,
                                  source_file: str | None = None) -> None:
    """
    Pre-populates resolved_vars[var_name] from ONE entry of a payload's
    "variables" object. Mutates resolved_vars in place.
    """
    from .generator import (
        resolve_wildcards, _parse_weighted_options,
        _resolve_count_expression, _ensure_var_bucket, _deck_draw,
    )

    _ensure_bucket = resolved_vars.get(var_name)
    if not isinstance(_ensure_bucket, dict):
        resolved_vars[var_name] = {}

    def _store(value: str):
        # Dynamically fetch the fresh reference to prevent orphaned scopes 
        # in the event nested payloads clear/replace the dictionary.
        current_bucket = resolved_vars.get(var_name)
        if not isinstance(current_bucket, dict):
            resolved_vars[var_name] = {}
            current_bucket = resolved_vars[var_name]
            
        # Find the next available JSON-specific origin index.
        json_index = 0
        while f"__json_{json_index}" in current_bucket:
            json_index += 1

        current_bucket[f"__json_{json_index}"] = value

    if isinstance(definition, list):
        definition = {"choices": definition}

    if isinstance(definition, dict):
        raw_choices = definition.get("choices", [])
        
        try:
            quantity_expr = str(definition.get("quantity", "1"))
        except Exception:
            quantity_expr = "1"

        items, weights, choice_metadata, choice_outputs = _build_choice_pool(raw_choices, resolved_vars)
        if not items:
            return

        try:
            quantity, exhaust_all = _resolve_count_expression(
                quantity_expr, var_rng, wildcard_dir,
                source_file=source_file, _resolved_vars=resolved_vars,
                bracket_ctx=None, bracket_overflow=True
            )
        except Exception as e:
            print(f"[Adaptive Prompts] Failed to resolve quantity for '{var_name}': {e}")
            quantity, exhaust_all = 1, False

        quantity = len(items) if exhaust_all else max(1, quantity)

        deck = {
            "all_items": list(items), "all_weights": list(weights),
            "remain_items": list(items), "remain_weights": list(weights),
        }
        
        collected = 0
        attempts = 0
        max_attempts = max(quantity * 10, 100) # Prevents infinite loops on permanent failures
        
        while collected < quantity and attempts < max_attempts:
            attempts += 1
            try:
                picked = _deck_draw(
                    deck,
                    var_rng.next_rng(),
                    allow_overflow=True
                )

                if picked is None:
                    break

                picked_str = _extract_and_apply_picked(
                    picked,
                    choice_metadata,
                    choice_outputs,
                    resolved_vars,
                    rng=var_rng.next_rng()
                )

                resolved = resolve_wildcards(
                    picked_str,
                    var_rng,
                    wildcard_dir,
                    source_file=source_file,
                    _resolved_vars=resolved_vars,
                    bracket_ctx=None,
                    bracket_overflow=True
                )

                # Only store and increment if it actually resolved to valid text
                if resolved and resolved.strip():
                    _store(resolved)
                    collected += 1
                else:
                    # Remove from master pool so it doesn't get redrawn on overflow, preventing early cancellation
                    if picked in deck["all_items"]:
                        deck["all_items"].remove(picked)
                    if exhaust_all:
                        # Consume the slot so we don't draw duplicates in exhaust mode
                        collected += 1
                        
            except Exception as e:
                print(f"[Adaptive Prompts] Error resolving choice for variable '{var_name}': {e}")
                # Same removal logic on thrown exceptions
                if 'picked' in locals() and picked in deck["all_items"]:
                    deck["all_items"].remove(picked)
                if exhaust_all:
                    collected += 1
                continue
    else:
        try:
            resolved = resolve_wildcards(
                str(definition), var_rng, wildcard_dir,
                source_file=source_file,
                _resolved_vars=resolved_vars,
                bracket_ctx=None, bracket_overflow=True
            )
            # Only store plain string definitions if they are valid
            if resolved and resolved.strip():
                _store(resolved)
        except Exception as e:
            print(f"[Adaptive Prompts] Error resolving variable '{var_name}': {e}")

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
                if flag_str in resolved_vars and isinstance(resolved_vars[flag_str], dict):
                    resolved_vars[flag_str].clear()
                else:
                    resolved_vars[flag_str] = {}
                resolved_vars[flag_str]["__set"] = "" 
            
    # Handle Dictionary format
    elif isinstance(set_data, dict):
        for k, v in set_data.items():
            k_str = str(k)
            
            if k_str in resolved_vars and isinstance(resolved_vars[k_str], dict):
                resolved_vars[k_str].clear()
            else:
                resolved_vars[k_str] = {}
                
            # Handle an array of multiple values for a single variable
            if isinstance(v, list):
                for i, val in enumerate(v):
                    resolved_vars[k_str][f"__set_{i}"] = str(val)
            else:
                # Handle a single scalar value
                resolved_vars[k_str]["__set"] = str(v)


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

    items, weights, choice_metadata, choice_outputs = _build_choice_pool(raw_generate, resolved_vars)
    if not items:
        return ""

    idx = _weighted_index(weights, rng)

    return _extract_and_apply_picked(
        items[idx],
        choice_metadata,
        choice_outputs,
        resolved_vars,
        rng=rng
    )


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
                # NEW: Allow the caller to reject a valid filepath
                if validator and not validator(candidate):
                    continue
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