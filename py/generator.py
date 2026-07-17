"""
Adaptive Prompts: generator
The brain of parsing bracket/file wildcards
Designed by Alectriciti

Changes:
- Removed arbitrary strip() in order to preserve likeness to the original prompt
  This allows for prompts like {2$${ and | }$$apple|banana|cherry} to function properly}
- Newlines are preserved
- Unified handling for __fruit__, __fruit^var__, and __^var__ tokens.
"""

import re
import os
import random
import hashlib
from .config import get_config
from .wildcard_utils import bfs_find_file

BRACKET_PATTERN = re.compile(r"\{([^{}]+)\}")

# Wildcards + variables:
# - name may include letters/digits/_/-/* and '/'
# - optional ^var after the name (var may include trailing *)
# - also supports pure variable recall: __^var__
FILE_PATTERN = re.compile(r"__(?:([A-Za-z0-9_\-/\*\.~]+))?(?:\^([A-Za-z0-9_\-\*]+))?__", re.UNICODE)

# Normalize spacing between adjacent wildcard-ish tokens (allow ^ and *)
ADJ_WC_PATTERN = re.compile(r"(__[a-zA-Z0-9_\-/*\^\*]+__)(__[a-zA-Z0-9_\-/*\^\*]+__)")

# marker used to separate adjacent wildcard tokens internally (removed at the end)
_ADJ_WC_MARKER = "<<ZWC>>"

DEFAULT_WILDCARD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wildcards")
)

# -------------------------------- RNG ---------------------------------------

class SeededRandom:
    def __init__(self, base_seed: int, mode: str = None, occurrence_counts: dict | None = None):
        self.base_seed = base_seed
        self.seed = base_seed
        
        if mode is None:
            self.mode = get_config("default_rng_mode")
        else:
            self.mode = mode
            
        self.occurrence_counts = occurrence_counts if occurrence_counts is not None else {}

    def branch(self, identity: str) -> 'SeededRandom':
        """Creates a new isolated SeededRandom based on the identity."""
        if self.mode == "Adaptive":
            count = self.occurrence_counts.get(identity, 0)
            self.occurrence_counts[identity] = count + 1
            
            # Create a stable, deterministic hash for cross-session consistency
            hash_str = f"{self.base_seed}_{identity}_{count}"
            stable_seed = int(hashlib.md5(hash_str.encode('utf-8')).hexdigest(), 16)
            
            # Return a new RNG branch that shares the global occurrence tracker
            return SeededRandom(stable_seed, mode=self.mode, occurrence_counts=self.occurrence_counts)
        else:
            # Legacy mode: advance sequentially and branch. This is the way Dynamic Prompts originally behaved.
            self.seed += 1
            return SeededRandom(self.seed, mode=self.mode, occurrence_counts=self.occurrence_counts)

    def next_rng(self) -> random.Random:
        """Advances the internal sequence and returns a standard random.Random instance."""
        self.seed += 1
        return random.Random(self.seed)

    def random(self) -> float:
        return self.next_rng().random()

    def uniform(self, a: float, b: float) -> float:
        return self.next_rng().uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        return self.next_rng().randint(a, b)

    def choice(self, seq):
        return self.next_rng().choice(seq)

# ------------------------- Quick taggers/helpers ----------------------------

def is_file_wildcard(choice: str) -> bool:
    # allow caller to pass padded choices; check trimmed for pattern match
    return bool(FILE_PATTERN.fullmatch(choice.strip()))

def _space_adjacent_wildcards(s: str) -> str:
    if not s:
        return s
    # Insert marker between the two matched wildcard tokens.
    return ADJ_WC_PATTERN.sub(r"\1" + _ADJ_WC_MARKER + r"\2", s)

# ---------------------- Wildcard blocking helpers -------------------------

# Regex to capture a backslash-escaped wildcard token: \__name__ or \__name^var__
_ESC_WC_RE = re.compile(r'\\(__[A-Za-z0-9_\-/*]+(?:\^[A-Za-z0-9_\-\*]+)?__)')

def _protect_escaped_wildcards(text: str, mapping: dict) -> str:
    """
    Replace occurrences like \__foo__ with unique placeholders.
    mapping is mutated: placeholder -> literal (without leading backslash).
    Returns new text.
    """
    if not text:
        return text
    def _repl(m):
        literal = m.group(1)  # e.g., "__foo__" or "__foo^var__"
        ph = f"<<LIT_WC_{len(mapping)}>>"
        mapping[ph] = literal
        return ph
    return _ESC_WC_RE.sub(_repl, text)

def _restore_escaped_wildcards(text: str, mapping: dict) -> str:
    """
    Replace placeholders back with their original literal wildcard text.
    """
    if not mapping:
        return text
    # Simple replace; placeholders are unique tokens unlikely to appear otherwise.
    for ph, literal in mapping.items():
        text = text.replace(ph, literal)
    return text

# ---------------------- Top-level split helpers ------------------------------

def _find_top_level_separators(s: str) -> list[tuple[int, str]]:
    """
    Returns a list of (index, token) where token is '$$' or '??'
    """
    results = []
    depth = 0
    i = 0
    L = len(s)

    while i < L:
        c = s[i]

        if c == "{":
            depth += 1
            i += 1
            continue
        if c == "}":
            if depth > 0:
                depth -= 1
            i += 1
            continue

        if depth == 0:
            if s.startswith("$$", i):
                results.append((i, "$$"))
                i += 2
                continue
            if s.startswith("??", i):
                results.append((i, "??"))
                i += 2
                continue

        i += 1

    return results

def _split_top_level_pipes(s: str) -> list[str]:
    """
    Split string on '|' tokens that are at top level (not inside nested {...}).
    IMPORTANT: do NOT trim returned segments — return exactly as found so leading/trailing
    spaces/newlines of each choice are preserved for correct spacing.
    """
    parts = []
    buf = []
    depth = 0
    i = 0
    L = len(s)
    while i < L:
        c = s[i]
        if c == "{":
            depth += 1
            buf.append(c)
        elif c == "}":
            if depth > 0:
                depth -= 1
            buf.append(c)
        elif c == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts

# ------------------------ Weighted file helpers -----------------------------

_WEIGHT_RE = re.compile(r'(?<!\\)%([0-9]*\.?[0-9]+)(?=\s*$)')

def _extract_choice_weight(choice: str) -> tuple[str, float]:
    """
    Extract trailing %weight from a bracket choice.
    Returns (clean_choice, weight).
    If no weight is present, weight defaults to 1.0.
    """
    m = _WEIGHT_RE.search(choice)
    if not m:
        return choice, 1.0

    weight = float(m.group(1))
    # remove ONLY the matched %weight token
    cleaned = choice[:m.start()] + choice[m.end():]
    return cleaned, weight

def _parse_weighted_options(lines_iterable):
    """
    Parse lines with optional %w% weight tag.
    Returns (items, weights). Defaults to weight 1.0 per item.
    """
    items, weights = [], []
    for raw in lines_iterable:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r'(?<!\\)#', line)[0].strip()
        if not line:
            continue
        m = re.search(r'(?<!\\)%([0-9]*\.?[0-9]+)%', line)
        if m:
            w = float(m.group(1))
            line = (line[:m.start()] + line[m.end():]).strip()
        else:
            w = 1.0
        line = line.replace(r'\%', '%')
        if line:
            items.append(line)
            weights.append(w)
    return items, weights

def _load_weighted_file(filepath: str):
    """
    Read a wildcard file and return (items, weights).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return _parse_weighted_options(f)
    except OSError:
        return [], []

def _weighted_index(weights, rng: random.Random) -> int:
    """
    Return an index sampled according to 'weights' (all non-negative).
    """
    if not weights:
        return 0
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(weights))
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if r <= acc:
            return i
    return len(weights) - 1

# -------------------------- Bracket deck context ----------------------------

def _ensure_deck_for_file(ctx: dict, filepath: str):
    """
    Ensure a deck for 'filepath' exists in ctx['decks'].
    A deck keeps a list of remaining items + weights (for NO-REPEAT draws),
    plus the full copies for refilling if overflow is enabled.
    """
    decks = ctx.setdefault("decks", {})
    if filepath in decks:
        return decks[filepath]
    items, weights = _load_weighted_file(filepath)
    deck = {
        "all_items": list(items),
        "all_weights": list(weights),
        "remain_items": list(items),
        "remain_weights": list(weights),
    }
    decks[filepath] = deck
    return deck

def _deck_draw(deck: dict, rng: random.Random, allow_overflow: bool) -> str | None:
    """
    Draw ONE item from a deck without replacement using remaining weights.
    If empty:
      - overflow=True  -> refill deck, then draw
      - overflow=False -> return None
    """
    if not deck["remain_items"]:
        if allow_overflow:
            deck["remain_items"] = list(deck["all_items"])
            deck["remain_weights"] = list(deck["all_weights"])
        else:
            return None
    if not deck["remain_items"]:
        return None
    idx = _weighted_index(deck["remain_weights"], rng)
    item = deck["remain_items"].pop(idx)
    deck["remain_weights"].pop(idx)
    return item

# ---------------------- File I/O / wildcard selection -----------------------

def _read_weighted_line(filepath: str, rng: random.Random) -> str:
    items, weights = _load_weighted_file(filepath)
    if not items:
        return ""
    idx = _weighted_index(weights, rng)
    return items[idx]

def _choose_file_from_dir(dir_path: str,
                          rng: random.Random,
                          prefix: str | None = None) -> str | None:
    if not os.path.isdir(dir_path):
        return None
    candidates = []
    try:
        for f in os.listdir(dir_path):
            if not f.lower().endswith(".txt"):
                continue
            name_no_ext = f[:-4]
            if prefix is None or name_no_ext.startswith(prefix):
                candidates.append(os.path.join(dir_path, f))
    except OSError:
        return None
    if not candidates:
        return None
    return rng.choice(candidates)

def resolve_wildcard_path(name: str, rng: random.Random, wildcard_dir: str, source_file: str | None) -> str | None:
    primary_dir = os.path.abspath(wildcard_dir) if wildcard_dir else DEFAULT_WILDCARD_ROOT
    
    # Determine local working directory
    if source_file and os.path.isfile(source_file):
        source_dir = os.path.dirname(os.path.abspath(source_file))
    else:
        source_dir = primary_dir

    # 1. Parse Explicit Prefixes
    is_explicit = False
    prefix_type = None
    search_dir = primary_dir

    if name.startswith("~/"):
        is_explicit = True
        prefix_type = "~"
        search_dir = primary_dir
        name = name[2:]
    elif name.startswith("./"):
        is_explicit = True
        prefix_type = "."
        search_dir = source_dir
        name = name[2:]
    elif name.startswith("../"):
        is_explicit = True
        prefix_type = ".."
        parent_dir = os.path.dirname(source_dir)
        # Fallback to root if we attempt to go higher than the root
        search_dir = parent_dir if source_dir != primary_dir else primary_dir
        name = name[3:]

    name = name.strip("/")
    if not name: 
        return None

    has_glob = "*" in name

    # --- Core Search Tools ---
    
    def _gather_globs(base_dir: str, pattern: str, allow_bfs: bool) -> list[str]:
        """Gathers candidates dynamically using RegEx translated from Globs."""
        import re
        candidates = []
        if not os.path.isdir(base_dir):
            return candidates
        
        # Convert glob to regex (e.g. * becomes [^/]*)
        regex_str = re.escape(pattern).replace(r"\*", r"[^/]*")
        
        if allow_bfs:
            # Matches strictly or inside any subdirectory
            final_regex = f"^({regex_str}|.*/{regex_str})$"
        else:
            # Matches strictly from base_dir 
            final_regex = f"^{regex_str}$"
            
        matcher = re.compile(final_regex)
        
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if not file.lower().endswith(".txt"):
                    continue
                    
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_dir)
                rel_name = rel_path[:-4].replace("\\", "/") # Normalize slashes
                
                if matcher.match(rel_name):
                    candidates.append(full_path)
        return candidates

    def _check_direct(base: str, target: str) -> str | None:
        """Fast explicit check for literal non-glob files."""
        filepath = os.path.normpath(os.path.join(base, f"{target}.txt"))
        return filepath if os.path.isfile(filepath) else None

    # --- 2. EXPLICIT RESOLUTION ---
    if is_explicit:
        if prefix_type == "~":
            # Literal root, zero fallback.
            if has_glob:
                cands = _gather_globs(search_dir, name, allow_bfs=False)
                return rng.choice(cands) if cands else None
            return _check_direct(search_dir, name)
        else:
            # Local/Parent Explicit: Gather all with BFS, zero fallback.
            if has_glob:
                cands = _gather_globs(search_dir, name, allow_bfs=True)
                return rng.choice(cands) if cands else None
            
            # Non-glob standard explicit check
            match = _check_direct(search_dir, name)
            if match: return match
            return bfs_find_file(search_dir, name)

    # --- 3. IMPLICIT RESOLUTION ---
    resolution_strategy = get_config("resolution_strategy")

    if has_glob:
        # GATHERING MODE
        # Step 1: Gather everything with BFS downwards from relative directory
        cands = _gather_globs(source_dir, name, allow_bfs=True)
        if cands: return rng.choice(cands)
        
        # Step 2: Fallback to root (depending on strategy)
        if source_dir != primary_dir:
            allow_bfs_root = (resolution_strategy == "Aggressive")
            cands_root = _gather_globs(primary_dir, name, allow_bfs=allow_bfs_root)
            if cands_root: return rng.choice(cands_root)
            
        return None
        
    else:
        # EXACT PATH MODE
        # Step 1: Immediate relative working directory
        match = _check_direct(source_dir, name)
        if match: return match

        # Step 2: BFS downwards from relative directory
        if source_dir != primary_dir:
            match = bfs_find_file(source_dir, name)
            if match: return match

        # Step 3: Immediate Root directory (No BFS fallback check)
        match = _check_direct(primary_dir, name)
        if match: return match

        # Step 4: Aggressive Mode (Full BFS from root)
        if resolution_strategy == "Aggressive" or source_file is None:
            match = bfs_find_file(primary_dir, name)
            if match: return match

        return None

def process_file_wildcard(name: str,
                          rng: random.Random,
                          wildcard_dir: str,
                          source_file: str | None = None,
                          bracket_ctx: dict | None = None) -> tuple[str, str | None]:
    """Returns the drawn text AND the filepath it was drawn from."""
    if not name:
        return "", None

    actual_fp = resolve_wildcard_path(name, rng, wildcard_dir, source_file)
    if not actual_fp:
        return "", None
        
    if bracket_ctx is None:
        return _read_weighted_line(actual_fp, rng), actual_fp
        
    deck = _ensure_deck_for_file(bracket_ctx, actual_fp)
    picked = _deck_draw(deck, rng, allow_overflow=bool(bracket_ctx.get("allow_overflow", True)))
    
    return picked or "", actual_fp

_VARNAME_RE = re.compile(r"[A-Za-z0-9_\-]+")

def sequence_prompt_elements(prompt: str, seed: int, mode: str, wildcard_dir: str, _resolved_vars: dict, rng: random.Random) -> str:
    """
    Deterministically sequences top-level wildcards and brackets using modulo math.
    """
    elements = []
    depth = 0
    i = 0
    L = len(prompt)

    # 1. Parse Top-Level Elements
    while i < L:
        if prompt[i] == "{":
            if depth == 0: start_idx = i
            depth += 1
        elif prompt[i] == "}":
            if depth > 0: depth -= 1
            if depth == 0:
                end_idx = i + 1
                var_name = None
                if end_idx < L and prompt[end_idx] == "^":
                    m_var = _VARNAME_RE.match(prompt, end_idx + 1)
                    if m_var:
                        var_name = m_var.group(0)
                        end_idx += 1 + len(var_name)

                inner = prompt[start_idx+1:i]
                separators = _find_top_level_separators(inner)
                choices_str = inner
                if separators:
                    idx = separators[-1][0]
                    choices_str = inner[idx + 2:]

                raw_choices = _split_top_level_pipes(choices_str)
                options = [_extract_choice_weight(c)[0] for c in raw_choices]

                if options:
                    elements.append({
                        'start': start_idx, 'end': end_idx,
                        'type': 'bracket', 'options': options,
                        'var_name': var_name
                    })
                i = end_idx - 1
        elif depth == 0 and prompt.startswith("__", i):
            m = FILE_PATTERN.match(prompt, i)
            if m:
                wc_name = m.group(1)
                var_tok = m.group(2)
                end_idx = m.end()

                if wc_name:
                    fp = resolve_wildcard_path(wc_name, rng, wildcard_dir, source_file=None)
                    if fp:
                        items, _ = _load_weighted_file(fp)
                        if items:
                            elements.append({
                                'start': i, 'end': end_idx,
                                'type': 'file', 'options': items,
                                'var_name': var_tok, 'wc_name': wc_name
                            })
                i = end_idx - 1
        i += 1

    if not elements: return prompt

    # 2. Calculate indices based on mode
    if mode == "PARALLEL":
        for el in elements:
            el['idx'] = seed % len(el['options'])
    elif mode == "FROM_START":
        divisor = 1
        for el in elements:
            opts = el['options']
            el['idx'] = (seed // divisor) % len(opts)
            divisor *= len(opts)
    elif mode == "FROM_END":
        divisor = 1
        for el in reversed(elements):
            opts = el['options']
            el['idx'] = (seed // divisor) % len(opts)
            divisor *= len(opts)

    # 3. Reconstruct string back-to-front
    result = prompt
    for el in reversed(elements):
        chosen = el['options'][el['idx']]
        if el['var_name']:
            _ensure_var_bucket(_resolved_vars, el['var_name'])
            if el['type'] == 'file':
                _resolved_vars[el['var_name']][el['wc_name']] = chosen
            else:
                origin_key = f"__bracket_{len(_resolved_vars[el['var_name']])}"
                _resolved_vars[el['var_name']][origin_key] = chosen

        result = result[:el['start']] + chosen + result[el['end']:]

    return result

def weighted_choice(options: list[str], rng: random.Random) -> str:
    items, weights = _parse_weighted_options(options)
    if not items:
        return ""
    idx = _weighted_index(weights, rng)
    return items[idx]

# ---------------------- Variable helpers ------------------------------------

def _ensure_var_bucket(_resolved_vars: dict, var_name: str):
    if var_name not in _resolved_vars:
        _resolved_vars[var_name] = {}


def _resolve_token(wc_name: str | None,
                    var_tok: str | None,
                    full_token: str,
                    seeded_rng: SeededRandom,
                    wildcard_dir: str,
                    source_file: str | None,
                    _resolved_vars: dict,
                    _depth: int,
                    bracket_ctx: dict | None,
                    bracket_overflow: bool,
                    escaped_map: dict | None,
                    strip_adj_marker: bool,
                    store_if_absent: bool,
                    lazy_rng: bool = False,
                    on_missing=None) -> str | None:
    """
    Resolves ONE __token__ match (already parsed by FILE_PATTERN into wc_name/var_tok).

    Single shared implementation for the iterative pass (_single_pass) and the
    _final_sweep_resolve cleanup pass, which previously re-implemented this 4-way
    branch independently and had quietly drifted apart.

    Token shapes handled:
      __^var__         -> pure variable recall (falls back to a same-named wildcard file)
      __name^var*__     -> origin-scoped recall across all vars matching the 'var' pattern
      __name^var__       -> assignment (draw + store), or origin-scoped recall if already stored
      __name__             -> plain wildcard draw

    store_if_absent:
        True  -> only write _resolved_vars[var_tok][wc_name] if not already set (first write wins).
        False -> always overwrite.

    lazy_rng:
        False -> draws the "choice" RNG before checking whether candidates exist
                 (burns a draw even on a miss). Matches original _single_pass behavior.
        True  -> only draws the "choice" RNG once it's known to be used.
                 Matches original _final_sweep_resolve behavior.
        (Only affects seed-stream position in Legacy RNG mode; Adaptive mode branches
        by content hash and is unaffected either way.)

    on_missing:
        Optional callable(kind: str, name: str) -> str, called instead of returning
        None when nothing could be resolved ('kind' is "variable" or "wildcard").
        If omitted, an unresolved token simply returns None.

    Returns the resolved replacement string (escape placeholders/markers intact --
    restored later on the full text), or None if unresolved with no on_missing given.
    """
    local_rng = seeded_rng.branch(f"wc_{wc_name}_{var_tok}")
    replacement = None

    def _is_real_change(generated: str) -> bool:
        if not generated:
            return False
        return generated != full_token and generated.strip() != full_token.strip()

    def _store(target_var: str, origin_key: str, value: str):
        _ensure_var_bucket(_resolved_vars, target_var)
        bucket = _resolved_vars[target_var]
        if store_if_absent and origin_key in bucket:
            return
        to_store = _restore_escaped_wildcards(value, escaped_map or {})
        if strip_adj_marker:
            to_store = to_store.replace(_ADJ_WC_MARKER, "")
        bucket[origin_key] = to_store

    if wc_name is None and var_tok:
        # __^var__  (pure variable recall)
        pre_rng = local_rng.next_rng() if not lazy_rng else None
        candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=None)
        if candidates:
            chooser = pre_rng or local_rng.next_rng()
            replacement = chooser.choice(candidates)
        else:
            rng_for_this = local_rng.next_rng()
            generated, generated_fp = process_file_wildcard(
                var_tok, rng_for_this, wildcard_dir, source_file, bracket_ctx=None
            )
            if _is_real_change(generated):
                replacement = resolve_wildcards(
                    generated, local_rng, wildcard_dir, source_file=generated_fp,
                    _depth=_depth + 1, _resolved_vars=_resolved_vars,
                    bracket_ctx=None, bracket_overflow=bracket_overflow
                )
        if replacement is None and on_missing is not None:
            replacement = on_missing("variable", var_tok)

    elif wc_name is not None and var_tok and "*" in var_tok:
        # __name^var*__  (origin-scoped recall across a var pattern)
        pre_rng = local_rng.next_rng() if not lazy_rng else None
        candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=wc_name)
        if candidates:
            chooser = pre_rng or local_rng.next_rng()
            replacement = chooser.choice(candidates)
        if replacement is None and on_missing is not None:
            replacement = on_missing("wildcard", wc_name)

    elif wc_name is not None and var_tok:
        # __name^var__  (assignment, or origin-scoped recall if already stored)
        bucket = _resolved_vars.get(var_tok, {})
        if wc_name in bucket:
            replacement = bucket[wc_name]
        else:
            rng_for_this = local_rng.next_rng()
            generated, generated_fp = process_file_wildcard(
                wc_name, rng_for_this, wildcard_dir, source_file, bracket_ctx=bracket_ctx
            )
            if _is_real_change(generated):
                replacement = resolve_wildcards(
                    generated, local_rng, wildcard_dir, source_file=generated_fp,
                    _depth=_depth + 1, _resolved_vars=_resolved_vars,
                    bracket_ctx=bracket_ctx, bracket_overflow=bracket_overflow
                )
                _store(var_tok, wc_name, replacement)
            if replacement is None and on_missing is not None:
                replacement = on_missing("wildcard", wc_name)

    else:
        # __name__  (plain wildcard)
        rng_for_this = local_rng.next_rng()
        generated, generated_fp = process_file_wildcard(
            wc_name, rng_for_this, wildcard_dir, source_file, bracket_ctx=bracket_ctx
        )
        if _is_real_change(generated):
            replacement = resolve_wildcards(
                generated, local_rng, wildcard_dir, source_file=generated_fp,
                _depth=_depth + 1, _resolved_vars=_resolved_vars,
                bracket_ctx=bracket_ctx, bracket_overflow=bracket_overflow
            )
        if replacement is None and on_missing is not None:
            replacement = on_missing("wildcard", wc_name)

    return replacement

def _collect_candidates(_resolved_vars: dict,
                        var_pat: str | None,
                        origin_filter: str | None) -> list[str]:
    """
    Build candidate strings for variable recall/shuffle using wildcard matching:
      var_pat == "*" -> all vars' values
      var_pat == "color*" -> var names starting with "color"
      var_pat == "alpha" -> var 'alpha' values
      origin_filter restricts to that origin key (e.g., "character").
    """
    if not _resolved_vars or not var_pat:
        return []
    
    import fnmatch
    candidates = []
    
    def add_values_for_var(vname: str):
        bucket = _resolved_vars.get(vname, {})
        if origin_filter is None:
            candidates.extend(bucket.values())
        else:
            if origin_filter in bucket:
                candidates.append(bucket[origin_filter])
                
    for vname in _resolved_vars.keys():
        if fnmatch.fnmatchcase(vname, var_pat):
            add_values_for_var(vname)
            
    return candidates

# ---------------------- Select Bracket to process -----------------------

def find_next_bracket_span(text: str):
    """
    Parse all bracket spans with a stack and decide which span should be processed next.
    Preference logic:
      - If any span has top-level $$ markers and contains nested spans inside its separator region,
        prefer that span (this prevents nested separators from being pre-resolved).
      - Otherwise, return the innermost span (max depth), earliest by start.
    Returns tuple (start_index, end_index) or None.
    """
    stack = []
    spans = []
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append(i)
        elif ch == "}":
            if stack:
                s = stack.pop()
                depth = len(stack) + 1
                spans.append((s, i, depth))
    if not spans:
        return None
    candidates = []
    for s, e, depth in spans:
        content = text[s+1:e]
        separators  = _find_top_level_separators(content)
        if len(separators ) >= 2:
            idx1, _ = separators[0]
            idx2, _ = separators[1]
            for ns, ne, nd in spans:
                if ns > s and ne < e:
                    nested_local_start = ns - (s + 1)
                    if nested_local_start >= idx1 + 2 and nested_local_start < idx2:
                        candidates.append((s, e, depth))
                        break
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return (candidates[0][0], candidates[0][1])
    max_depth = max(sp[2] for sp in spans)
    outers = [sp for sp in spans if sp[2] == 1]
    outers.sort(key=lambda x: x[0])
    return (outers[0][0], outers[0][1])



def _join_results(results: list[str],
                   separator: str,
                   final_separator: str | None,
                   seeded_rng: SeededRandom,
                   wildcard_dir: str,
                   source_file: str | None,
                   _resolved_vars: dict,
                   bracket_ctx: dict) -> str:
    """
    Joins resolved bracket choices with `separator`, except between the last
    two items, where `final_separator` is used instead if one was given.

    Powers the "Oxford comma" style syntax:
        {3$$, $$, and $$a|b|c}  ->  "a, b, and c"
        {2$$, $$ and $$a|b}     ->  "a and b"   (only 2 items: final_separator only)

    Both separators are resolved fresh per join (so wildcards/brackets inside
    a separator still work), matching the existing separator behavior.
    """
    if not results:
        return ""

    def _resolve_sep(sep_text: str) -> str:
        sep_seed = seeded_rng.next_rng().getrandbits(64)
        sep_rng = SeededRandom(sep_seed, mode=seeded_rng.mode, occurrence_counts=seeded_rng.occurrence_counts)
        return resolve_wildcards(
            sep_text, sep_rng, wildcard_dir, source_file=source_file,
            _resolved_vars=_resolved_vars,
            bracket_ctx=bracket_ctx,
            bracket_overflow=bracket_ctx["allow_overflow"]
        )

    joined = results[0]
    last_idx = len(results) - 1
    for i, item in enumerate(results[1:], start=1):
        use_final = (final_separator is not None) and (i == last_idx)
        sep_text = final_separator if use_final else separator
        joined += _resolve_sep(sep_text) + item

    return joined

# ---------------------- Bracket processing ----------------------------------

def process_bracket(content: str,
                    seeded_rng: SeededRandom,
                    wildcard_dir: str,
                    source_file: str | None = None,
                    _resolved_vars=None,
                    bracket_ctx: dict | None = None,
                    bracket_overflow: bool = True) -> str:
    """
    Handles bracket syntax:
      - Deck Mode (using $$ as the separator) utilizes NO-REPEAT until all possible options have been exhausted.
      - Roulette Mode (using ?? as the separator) only considers the weights. Repeats are possible.
      - choices split with '|'
      - consider choice weights with %#.###
      - nested bracket/wildcard resolution for both choices and separators
    """
    count = 1
    exhaust_all = False
    separator = ", "
    final_separator = None  # NEW: separator used only between the last two items
    choices_str = content

    if bracket_ctx is None:
        bracket_ctx = {"allow_overflow": bool(bracket_overflow), "decks": {}}
    else:
        bracket_ctx.setdefault("allow_overflow", bool(bracket_overflow))
        bracket_ctx.setdefault("decks", {})

    separators = _find_top_level_separators(content)
    token = "$$"

    if separators:
        if len(separators) == 1:
            idx, token = separators[0]
            count_part = content[:idx]
            choices_str = content[idx + 2:]
        elif len(separators) == 2:
            idx1, token = separators[0]
            idx2, _ = separators[1]
            count_part = content[:idx1]
            raw_separator = content[idx1 + 2:idx2]
            choices_str = content[idx2 + 2:]

            try:
                separator = raw_separator.encode("utf-8").decode("unicode_escape")
            except Exception:
                separator = raw_separator
        else:
            # 3+ separators: count$$sep$$final_sep$$choices
            # Only the first three tokens are treated structurally; any further
            # top-level $$/?? tokens fall inside choices_str as literal text,
            # same as how a would-be 3rd token was already treated before this change.
            idx1, token = separators[0]
            idx2, _ = separators[1]
            idx3, _ = separators[2]
            count_part = content[:idx1]
            raw_separator = content[idx1 + 2:idx2]
            raw_final_separator = content[idx2 + 2:idx3]
            choices_str = content[idx3 + 2:]

            try:
                separator = raw_separator.encode("utf-8").decode("unicode_escape")
            except Exception:
                separator = raw_separator

            try:
                final_separator = raw_final_separator.encode("utf-8").decode("unicode_escape")
            except Exception:
                final_separator = raw_final_separator
        
        resolved_count = resolve_wildcards(
            count_part, 
            seeded_rng, 
            wildcard_dir,
            source_file=source_file,
            _resolved_vars=_resolved_vars,
            bracket_ctx=bracket_ctx,
            bracket_overflow=bracket_overflow
        ).strip()
        
        if resolved_count == "*":
            exhaust_all = True
        elif "-" in resolved_count:
            try:
                lo_str, hi_str = resolved_count.split("-", 1)
                lo = int(lo_str.strip())
                hi = int(hi_str.strip())
                count = seeded_rng.next_rng().randint(lo, hi)
            except ValueError:
                count = 1
        else:
            try:
                count = int(resolved_count)
            except ValueError:
                pass

    selection_mode = "roulette" if token == "??" else "deck"

    raw_choices = _split_top_level_pipes(choices_str)

    choice_keys = []
    weights = []

    for c in raw_choices:
        clean, w = _extract_choice_weight(c)
        weights.append(w)

        trimmed = clean.strip()
        m = FILE_PATTERN.fullmatch(trimmed)

        if m:
            wc_name = m.group(1)
            var_tok = m.group(2)
            if wc_name is None and var_tok:
                key = ("var", var_tok, clean, var_tok)
            else:
                key = ("file", wc_name.strip() if wc_name else "", clean, var_tok)
        else:
            key = ("lit", trimmed, clean, None)

        choice_keys.append(key)

    # Remove deduplication entirely
    unique_keys = choice_keys.copy()

    # --- Handle * (exhaust all) mode ---
    if exhaust_all:
        pool_items = []

        # Intercept single file/variable choices and dynamically extrapolate their items into the pool
        if len(unique_keys) == 1 and unique_keys[0][0] in ("file", "var"):
            key = unique_keys[0]
            kind, canonical, original, var_tok = key

            if kind == "var":
                vals = _collect_candidates(_resolved_vars, canonical, origin_filter=None)
                for v in vals:
                    pool_items.append((v, "lit", None, None, None))
            elif kind == "file":
                eval_rng_for_path = seeded_rng.next_rng()
                actual_fp = resolve_wildcard_path(canonical, eval_rng_for_path, wildcard_dir, source_file)
                if actual_fp:
                    items, _ = _load_weighted_file(actual_fp)
                    for item in items:
                        pool_items.append((item, "file_line", var_tok, canonical, actual_fp))
        else:
            for key in unique_keys:
                kind, canonical, original, var_tok = key
                if kind == "var":
                    vals = _collect_candidates(_resolved_vars, canonical, origin_filter=None)
                    for v in vals:
                        pool_items.append((v, "lit", None, None, None))
                else:
                    pool_items.append((original, kind, var_tok, canonical, None))

        # Engage roulette permutation to completely shuffle the extracted results
        if selection_mode == "roulette":
            seeded_rng.next_rng().shuffle(pool_items)

        results = []
        for item_val, kind, var_tok, canonical, actual_fp in pool_items:
            eval_seed = seeded_rng.next_rng().getrandbits(64)
            eval_rng = SeededRandom(eval_seed, mode=seeded_rng.mode, occurrence_counts=seeded_rng.occurrence_counts)

            if kind == "lit":
                resolved = resolve_wildcards(
                    item_val, eval_rng, wildcard_dir, source_file=source_file,
                    _resolved_vars=_resolved_vars,
                    bracket_ctx=None,
                    bracket_overflow=True
                )
                if resolved != "":
                    results.append(resolved)
            elif kind == "file_line":
                resolved = resolve_wildcards(
                    item_val, eval_rng, wildcard_dir, source_file=actual_fp,
                    _resolved_vars=_resolved_vars,
                    bracket_ctx=bracket_ctx,
                    bracket_overflow=True
                )
                if var_tok:
                    _ensure_var_bucket(_resolved_vars, var_tok)
                    _resolved_vars[var_tok].setdefault(canonical, resolved)
                if resolved != "":
                    results.append(resolved)
            else:
                resolved = resolve_wildcards(
                    item_val, eval_rng, wildcard_dir, source_file=source_file,
                    _resolved_vars=_resolved_vars,
                    bracket_ctx=bracket_ctx if kind == "file" else None,
                    bracket_overflow=True
                )
                if resolved != "":
                    results.append(resolved)

        # Reconstruct output string
        if results:
            return _join_results(
                results, separator, final_separator,
                seeded_rng, wildcard_dir, source_file, _resolved_vars, bracket_ctx
            )
        else:
            return ""

    rng = seeded_rng.next_rng()

    def weighted_pick(pool):
        idx = _weighted_index(
            [weights[choice_keys.index(k)] for k in pool],
            rng
        )
        return pool[idx]

    def resolve_choice(key):
        kind, canonical, original, var_tok = key

        eval_seed = seeded_rng.next_rng().getrandbits(64)
        eval_rng = SeededRandom(eval_seed, mode=seeded_rng.mode, occurrence_counts=seeded_rng.occurrence_counts)

        if kind == "lit":
            return resolve_wildcards(
                original, eval_rng, wildcard_dir, source_file=source_file,
                _resolved_vars=_resolved_vars,
                bracket_ctx=None,
                bracket_overflow=True
            )

        # Route variables directly into standard contextual deck system logic to block repeats
        if kind == "var":
            vals = _collect_candidates(_resolved_vars, canonical, None)
            if not vals:
                return ""
            deck_key = f"var:{canonical}"
            if deck_key not in bracket_ctx["decks"]:
                bracket_ctx["decks"][deck_key] = {
                    "all_items": list(vals),
                    "all_weights": [1.0] * len(vals),
                    "remain_items": list(vals),
                    "remain_weights": [1.0] * len(vals),
                }
            deck = bracket_ctx["decks"][deck_key]
            picked = _deck_draw(deck, rng, allow_overflow=bracket_ctx["allow_overflow"])
            return picked or ""

        drawn_text, drawn_fp = process_file_wildcard(canonical, rng, wildcard_dir, source_file, bracket_ctx)
        if not drawn_text:
            return ""

        resolved = resolve_wildcards(
            drawn_text, eval_rng, wildcard_dir, source_file=drawn_fp,
            _resolved_vars=_resolved_vars,
            bracket_ctx=bracket_ctx,
            bracket_overflow=bracket_ctx["allow_overflow"]
        )

        if var_tok:
            _ensure_var_bucket(_resolved_vars, var_tok)
            _resolved_vars[var_tok].setdefault(canonical, resolved)

        return resolved

    results = []
    deck = list(unique_keys)

    while len(results) < count:
        if selection_mode == "deck":
            if not deck:
                if not bracket_ctx["allow_overflow"]:
                    break
                deck = list(unique_keys)

            key = weighted_pick(deck)
            deck.remove(key)
        else:
            key = weighted_pick(unique_keys)

        results.append(resolve_choice(key))

    if not results:
        return ""

    return _join_results(
        results, separator, final_separator,
        seeded_rng, wildcard_dir, source_file, _resolved_vars, bracket_ctx
    )

# ---------------------- Main resolver (iterative passes + final sweep) ------------

def _format_origin(source_file: str | None, wildcard_dir: str) -> str:
    """Helper to format the origin path neatly for the console."""
    if not source_file:
        return "root"
    try:
        # Returns clean paths like 'characters/face.txt'
        return os.path.relpath(source_file, wildcard_dir)
    except ValueError:
        return source_file

_VARNAME_RE = re.compile(r"[A-Za-z0-9_\-]+")

def _final_sweep_resolve(text: str,
                         seeded_rng: SeededRandom,
                         wildcard_dir: str,
                         source_file: str | None,
                         _resolved_vars: dict,
                         _depth: int,
                         escaped_map: dict | None = None) -> str:
    """
    Final left-to-right pass that tries to resolve any remaining variable/wildcard tokens.
    This is executed once after the iterative passes to rescue __^var__ style tokens that
    could not be resolved earlier. Handles error injection for missing tokens.
    """
    missing_mode = get_config("missing_wildcard_behavior")
    origin_str = _format_origin(source_file, wildcard_dir)
    
    def _handle_missing(kind: str, name: str) -> str:
        """Helper to process missing variable/wildcard text and logs based on settings."""
        if missing_mode == "Inject Warning":
            display_name = f"^{name}" if kind == "variable" else name
            print(f"\033[31m[Adaptive Prompts] ERROR:\033[0m {kind} __{display_name}__ not found. origin: {origin_str}")
            return f"!!!{kind.upper()} \"{name}\" NOT FOUND!!!"
        return ""
    
    i = 0
    while True:
        m = FILE_PATTERN.search(text, i)
        if not m:
            break
        full_token = m.group(0)
        wc_name = m.group(1)
        var_tok = m.group(2)

        replacement = _resolve_token(
            wc_name, var_tok, full_token,
            seeded_rng, wildcard_dir, source_file,
            _resolved_vars, _depth,
            bracket_ctx=None,
            bracket_overflow=True,
            escaped_map=escaped_map,
            strip_adj_marker=True,
            store_if_absent=False,
            lazy_rng=True,
            on_missing=_handle_missing,
        )

        text = text[:m.start()] + replacement + text[m.end():]
        i = m.start() + len(replacement)

    return text

def resolve_wildcards(text: str,
                      seeded_rng: SeededRandom,
                      wildcard_dir: str,
                      source_file: str | None = None,
                      _depth=0,
                      _resolved_vars=None,
                      bracket_ctx: dict | None = None,
                      bracket_overflow: bool = True) -> str:
    """
    Iterative resolver:
      - Runs passes until no further replacements occur (or max passes reached).
      - Keeps unresolved variable/wildcard tokens intact for later passes instead of deleting them.
      - Uses placeholders during a pass to avoid infinite loops on unresolved tokens.
      - Shares a per-bracket deck context when called by process_bracket so that
        file wildcard draws avoid repeats within that bracket.
      - After the normal iterative passes, runs a final sweep attempting to resolve
        any remaining variable/wildcard tokens once more; removes ones that cannot be resolved.
    """
    search_depth_limit = get_config("search_depth_limit")
    if _depth > search_depth_limit:
        return text

    if _resolved_vars is None:
        _resolved_vars = {}

    # preserve whitespace/newlines: only ensure adjacent wildcard tokens separated
    text = _space_adjacent_wildcards(text)

    # PROTECT escaped wildcards (e.g. "\__color__") so they won't be processed. Will be restored later.
    _escaped_wildcard_map = {}
    text = _protect_escaped_wildcards(text, _escaped_wildcard_map)

    placeholder_counter = 0
    placeholders = {}

    def next_placeholder():
        nonlocal placeholder_counter
        ph = f"<<UNRES_{placeholder_counter}>>"
        placeholder_counter += 1
        return ph

    max_passes = 12
    pass_no = 0
    while pass_no < max_passes:
        pass_no += 1
        changed = False

        def _single_pass(s_text: str) -> str:
            nonlocal changed, placeholders
            working = s_text

            while True:
                m_file = FILE_PATTERN.search(working)
                br_span = find_next_bracket_span(working)
                if br_span:
                    br_start, br_end = br_span
                else:
                    br_start = br_end = None

                if not m_file and not br_span:
                    break

                if m_file and br_span:
                    take_bracket = (br_start < m_file.start())
                else:
                    take_bracket = bool(br_span)

                if take_bracket:
                    content = working[br_start + 1: br_end]
                    
                    # --- NEW: Calculate Bracket Identity ---
                    separators = _find_top_level_separators(content)
                    if separators:
                        if len(separators) == 1:
                            count_part = content[:separators[0][0]]
                            choices_str = content[separators[0][0] + 2:]
                        else:
                            count_part = content[:separators[0][0]]
                            choices_str = content[separators[1][0] + 2:]
                    else:
                        count_part = "1"
                        choices_str = content
                    
                    num_choices = len(_split_top_level_pipes(choices_str))
                    bracket_identity = f"bracket_{count_part.strip()}_{num_choices}"
                    
                    # Create our isolated RNG branch for this bracket
                    local_rng = seeded_rng.branch(bracket_identity)

                    # Now pass local_rng instead of seeded_rng!
                    repl = process_bracket(
                        content,
                        local_rng,
                        wildcard_dir,
                        source_file=source_file,
                        _resolved_vars=_resolved_vars,
                        bracket_ctx=bracket_ctx,
                        bracket_overflow=bracket_overflow
                    )

                    chain_assigned_values = []
                    replace_end = br_end + 1
                    pos = br_end + 1
                    made_assignment = False

                    while pos < len(working) and working[pos] == "^":
                        m_var = _VARNAME_RE.match(working, pos + 1)
                        if not m_var:
                            break
                        var_name = m_var.group(0)

                        if not chain_assigned_values:
                            value_to_store = repl
                        else:
                            prev_set = set(chain_assigned_values)
                            max_attempts = 50 * (len(prev_set) + 1)
                            attempt = 0
                            value_to_store = None
                            last_try = None
                            while attempt < max_attempts:
                                attempt += 1
                                candidate = process_bracket(
                                    content, local_rng, wildcard_dir, source_file=source_file,
                                    _resolved_vars=_resolved_vars,
                                    bracket_ctx=bracket_ctx,
                                    bracket_overflow=bracket_overflow
                                )
                                last_try = candidate
                                if candidate not in prev_set:
                                    value_to_store = candidate
                                    break
                            if value_to_store is None:
                                value_to_store = last_try if last_try is not None else repl

                        # restore escaped placeholders before storing in context and before appending for output
                        restored_value = _restore_escaped_wildcards(value_to_store, _escaped_wildcard_map or {})
                        # strip internal adjacent-wildcard marker before storing/returning
                        restored_value = restored_value.replace(_ADJ_WC_MARKER, "")

                        _ensure_var_bucket(_resolved_vars, var_name)
                        bucket = _resolved_vars[var_name]
                        origin_key = f"__bracket_{len(bucket)}"
                        bucket[origin_key] = restored_value

                        chain_assigned_values.append(restored_value)

                        replace_end = pos + 1 + len(var_name)
                        pos = replace_end
                        made_assignment = True

                    if made_assignment:
                        output = ", ".join(chain_assigned_values)
                        working = working[:br_start] + output + working[replace_end:]
                    else:
                        working = working[:br_start] + repl + working[br_end + 1:]

                    working = _space_adjacent_wildcards(working)
                    continue

                full_token = m_file.group(0)
                wc_name = m_file.group(1)
                var_tok = m_file.group(2)

                replacement = _resolve_token(
                    wc_name, var_tok, full_token,
                    seeded_rng, wildcard_dir, source_file,
                    _resolved_vars, _depth,
                    bracket_ctx=bracket_ctx,
                    bracket_overflow=bracket_overflow,
                    escaped_map=_escaped_wildcard_map,
                    strip_adj_marker=False,
                    store_if_absent=True,
                    lazy_rng=False,
                )

                if replacement is None:
                    ph = next_placeholder()
                    placeholders[ph] = full_token
                    working = working[:m_file.start()] + ph + working[m_file.end():]
                else:
                    working = working[:m_file.start()] + replacement + working[m_file.end():]
                    changed = True
                    working = _space_adjacent_wildcards(working)

            return working

        new_text = _single_pass(text)

        if placeholders:
            for ph, orig in placeholders.items():
                new_text = new_text.replace(ph, orig)
            placeholders = {}
            placeholder_counter = 0

        if not changed:
            text = new_text
            break

        text = new_text
        text = _space_adjacent_wildcards(text)

    # Final sweep (no bracket context here)
    text = _final_sweep_resolve(
        text, seeded_rng, wildcard_dir, source_file, _resolved_vars, _depth,
        escaped_map=_escaped_wildcard_map
    )
    # RESTORE any protected escaped wildcard placeholders back to literal text
    text = _restore_escaped_wildcards(text, _escaped_wildcard_map)
    text = text.replace(_ADJ_WC_MARKER, "")
    return text

def evaluate_prompt_core(prompt: str, rng: SeededRandom, wildcard_dir: str, resolved_vars: dict, hide_comments: bool = True) -> str:
    """
    Evaluates comments blocks first, optionally removes them, then evaluates the main prompt string.
    This is the core execution logic shared by PromptGenerator and PromptStackLoader.
    """
    if hide_comments is None:
        hide_comments = get_config("hide_comments")
    
    comment_blocks = re.findall(r"##(.*?)##", prompt, flags=re.DOTALL)
    for block in comment_blocks:
        _ = resolve_wildcards(block, rng, wildcard_dir, source_file=None, _resolved_vars=resolved_vars)

    if hide_comments:
        prompt = re.sub(r"##.*?##", "", prompt, flags=re.DOTALL)

    return resolve_wildcards(prompt, rng, wildcard_dir, source_file=None, _resolved_vars=resolved_vars)