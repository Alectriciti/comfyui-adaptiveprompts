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


BRACKET_PATTERN = re.compile(r"\{([^{}]+)\}")

# Wildcards + variables:
# - name may include letters/digits/_/-/* and '/'
# - optional ^var after the name (var may include trailing *)
# - also supports pure variable recall: __^var__
FILE_PATTERN = re.compile(r"__(?:([a-zA-Z0-9_\-/*]+?))?(?:\^([a-zA-Z0-9_\-\*]+))?__")

# Normalize spacing between adjacent wildcard-ish tokens (allow ^ and *)
ADJ_WC_PATTERN = re.compile(r"(__[a-zA-Z0-9_\-/*\^\*]+__)(__[a-zA-Z0-9_\-/*\^\*]+__)")

DEFAULT_WILDCARD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "wildcards")
)

# -------------------------------- RNG ---------------------------------------

class SeededRandom:
    def __init__(self, base_seed: int):
        self.seed = base_seed

    def next_rng(self) -> random.Random:
        """
        Advances the seed and returns a new Random instance.
        """
        self.seed += 1
        return random.Random(self.seed)

    def random(self) -> float:
        rng = self.next_rng()
        return rng.random()

    def uniform(self, a: float, b: float) -> float:
        rng = self.next_rng()
        return rng.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        rng = self.next_rng()
        return rng.randint(a, b)

    def choice(self, seq):
        rng = self.next_rng()
        return rng.choice(seq)

# ------------------------- Quick taggers/helpers ----------------------------

def is_file_wildcard(choice: str) -> bool:
    # allow caller to pass padded choices; check trimmed for pattern match
    return bool(FILE_PATTERN.fullmatch(choice.strip()))

def _space_adjacent_wildcards(s: str) -> str:
    # ensures adjacent wildcard tokens are separated by a space
    return ADJ_WC_PATTERN.sub(r"\1 \2", s)

# ---------------------- Top-level split helpers ------------------------------

def _find_top_level_dollars(s: str) -> list[int]:
    indices = []
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
        if depth == 0 and s.startswith("$$", i):
            indices.append(i)
            i += 2
            continue
        i += 1
    return indices

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

def process_file_wildcard(name: str,
                          rng: random.Random,
                          wildcard_dir: str,
                          bracket_ctx: dict | None = None) -> str:
    """
    file patterns supported (same as before). This version will:
      - Try to resolve files relative to the provided wildcard_dir first.
      - If a file/directory is missing there, attempt the equivalent path under
        DEFAULT_WILDCARD_ROOT (the global '/wildcards/' fallback).
      - If bracket_ctx is provided, draws are done WITHOUT replacement from a deck
        (per-file) for the lifetime of this bracket; the deck key is the actual
        filepath used (primary or fallback).
    """
    if not name:
        return ""

    # Normalize the incoming wildcard_dir (may be absolute path passed from PromptGenerator)
    primary_dir = wildcard_dir or DEFAULT_WILDCARD_ROOT

    # Helper: given a candidate absolute filepath (built from primary_dir), try using it,
    # otherwise compute the fallback filepath and use that if it exists.
    def _resolve_filepath(candidate_fp: str) -> str | None:
        # If candidate exists, use it
        if candidate_fp and os.path.exists(candidate_fp):
            return candidate_fp
        # Try to compute a fallback path by converting from primary_dir -> DEFAULT_WILDCARD_ROOT
        try:
            rel = os.path.relpath(candidate_fp, primary_dir)
        except Exception:
            rel = os.path.basename(candidate_fp) if candidate_fp else ""
        if rel:
            fallback_fp = os.path.join(DEFAULT_WILDCARD_ROOT, rel)
            if os.path.exists(fallback_fp):
                return fallback_fp
        return None

    def draw_from_filepath(filepath: str) -> str:
        # resolve actual filepath (primary -> fallback)
        actual_fp = _resolve_filepath(filepath)
        if not actual_fp:
            return ""
        # If no bracket context, do legacy single weighted draw
        if bracket_ctx is None:
            return _read_weighted_line(actual_fp, rng)
        # Decked draw (no-repeat in this bracket) keyed by actual filepath
        deck = _ensure_deck_for_file(bracket_ctx, actual_fp)
        picked = _deck_draw(deck, rng, allow_overflow=bool(bracket_ctx.get("allow_overflow", True)))
        return picked or ""

    # If name references a subfolder / file
    name = name.strip("/")

    if "/" in name:
        dir_part, last = name.rsplit("/", 1)
        dir_path = os.path.join(primary_dir, dir_part)

        if last == "" or last == "*" or last.endswith("*"):
            prefix = None if last in ("", "*") else last[:-1]
            chosen = _choose_file_from_dir(dir_path, rng, prefix=prefix)
            if not chosen:
                # try fallback directory
                try:
                    rel_dir = os.path.relpath(dir_path, primary_dir)
                except Exception:
                    rel_dir = os.path.basename(dir_path)
                fallback_dir = os.path.join(DEFAULT_WILDCARD_ROOT, rel_dir)
                chosen = _choose_file_from_dir(fallback_dir, rng, prefix=prefix)
            return draw_from_filepath(chosen) if chosen else ""

        filepath = os.path.join(dir_path, f"{last}.txt")
        # try primary then fallback
        return draw_from_filepath(filepath)

    # Root-level cases
    if name == "*":
        chosen = _choose_file_from_dir(primary_dir, rng, prefix=None)
        if not chosen:
            # fallback to default root
            chosen = _choose_file_from_dir(DEFAULT_WILDCARD_ROOT, rng, prefix=None)
        return draw_from_filepath(chosen) if chosen else ""

    if name.endswith("*"):
        prefix = name[:-1]
        chosen = _choose_file_from_dir(primary_dir, rng, prefix=prefix)
        if not chosen:
            # fallback to default root
            chosen = _choose_file_from_dir(DEFAULT_WILDCARD_ROOT, rng, prefix=prefix)
        return draw_from_filepath(chosen) if chosen else ""

    # Specific file in primary dir -> fallback to default if missing
    filepath = os.path.join(primary_dir, f"{name}.txt")
    return draw_from_filepath(filepath)

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

def _collect_candidates(_resolved_vars: dict,
                        var_pat: str | None,
                        origin_filter: str | None) -> list[str]:
    """
    Build candidate strings for variable recall/shuffle:
      var_pat == "*" -> all vars' values
      var_pat == "a*" -> var names starting with "a"
      var_pat == "alpha" -> var 'alpha' values
      origin_filter restricts to that origin key (e.g., "character").
    """
    if not _resolved_vars or not var_pat:
        return []
    match_all = (var_pat == "*")
    prefix = ""
    exact_name = None
    if match_all:
        pass
    elif var_pat.endswith("*"):
        prefix = var_pat[:-1]
    else:
        exact_name = var_pat
    candidates = []
    def add_values_for_var(vname: str):
        bucket = _resolved_vars.get(vname, {})
        if origin_filter is None:
            candidates.extend(bucket.values())
        else:
            if origin_filter in bucket:
                candidates.append(bucket[origin_filter])
    if match_all:
        for vname in _resolved_vars.keys():
            add_values_for_var(vname)
    elif exact_name is not None:
        add_values_for_var(exact_name)
    else:
        for vname in _resolved_vars.keys():
            if vname.startswith(prefix):
                add_values_for_var(vname)
    return candidates

# ---------------------- New: select bracket to process -----------------------

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
        dollar_idxs = _find_top_level_dollars(content)
        if len(dollar_idxs) >= 2:
            idx1 = dollar_idxs[0]
            idx2 = dollar_idxs[1]
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
    inners = [sp for sp in spans if sp[2] == max_depth]
    inners.sort(key=lambda x: x[0])
    return (inners[0][0], inners[0][1])

# ---------------------- Bracket processing ----------------------------------

def process_bracket(content: str,
                    seeded_rng: SeededRandom,
                    wildcard_dir: str,
                    _resolved_vars=None,
                    bracket_ctx: dict | None = None,
                    bracket_overflow: bool = True) -> str:
    """
    Handles bracket syntax with:
      - count and optional custom separators using $$ markers
      - choices split with '|'
      - nested bracket/wildcard resolution for both choices and separators
      - NO-REPEAT within this bracket using a per-bracket deck context:
          * For file wildcards: draw without replacement from that file until exhausted.
          * For top-level choices: each is used once before any repeats.
        Repeats are allowed only if bracket_overflow=True.

    Examples:
      {4$$__fruit__}                              -> one of each fruit first, then repeats if needed
      {6$$__fruit__}                              -> use all fruits once, then start repeating
      {10$$__fruit__|__instrument__}              -> mix, both files use their own decks
      {5$$__fruit__|__instrument__|__animal__}    -> first 3 cover each choice once in random order,
                                                     remaining 2 only if overflow=True
    """
    # Default
    count = 1
    separator = ", "
    choices_str = content

    # Ensure/seed a bracket context for deck/no-repeat behavior
    if bracket_ctx is None:
        bracket_ctx = {"allow_overflow": bool(bracket_overflow), "decks": {}}
    else:
        bracket_ctx.setdefault("allow_overflow", bool(bracket_overflow))
        bracket_ctx.setdefault("decks", {})

    # Find top-level $$ markers (ignoring nested brackets)
    dollar_idxs = _find_top_level_dollars(content)

    if not dollar_idxs:
        choices_str = content
    elif len(dollar_idxs) == 1:
        idx1 = dollar_idxs[0]
        count_part = content[:idx1]
        choices_str = content[idx1 + 2 :]
        if "-" in count_part:
            low, high = map(int, count_part.split("-", 1))
            count = seeded_rng.next_rng().randint(low, high)
        else:
            try:
                count = int(count_part)
            except Exception:
                count = 1
    else:
        idx1 = dollar_idxs[0]
        idx2 = dollar_idxs[1]
        count_part = content[:idx1]
        raw_separator = content[idx1 + 2 : idx2]
        choices_str = content[idx2 + 2 :]

        if "-" in count_part:
            low, high = map(int, count_part.split("-", 1))
            count = seeded_rng.next_rng().randint(low, high)
        else:
            try:
                count = int(count_part)
            except Exception:
                count = 1

        try:
            separator = raw_separator.encode("utf-8").decode("unicode_escape")
        except Exception:
            separator = raw_separator

    # Split choices by top-level pipes (do NOT strip — preserve exact choice content)
    raw_choices = [c for c in _split_top_level_pipes(choices_str) if c != ""]
    
    # This isolates all bracket randomness from outer calls while still being deterministic.
    bracket_seed_source = seeded_rng.next_rng()  # consumes from global RNG
    bracket_seed_value = bracket_seed_source.getrandbits(64)
    bracket_seeded = SeededRandom(bracket_seed_value)

    rng = bracket_seeded.next_rng()

    # Build enriched choice triplets.
    # Each key is a tuple: (kind, canonical, original, var_tok)
    # kind in {"lit", "file", "var"}
    choice_keys = []
    for c in raw_choices:
        original = c  # exact user text (preserve whitespace/newlines)
        trimmed = c.strip()

        m = None
        if FILE_PATTERN.fullmatch(trimmed):
            m = FILE_PATTERN.fullmatch(trimmed)

        if m:
            wc_name = m.group(1)  # may be None for pure var recall
            var_tok = m.group(2)  # may be None
            if (wc_name is None or wc_name == "") and var_tok:
                # pure variable recall token: __^var__
                kind = "var"
                canonical = var_tok
                key = (kind, canonical, original, var_tok)
            else:
                # a file wildcard (may include a ^var assignment)
                kind = "file"
                canonical = (wc_name or "").strip()
                key = (kind, canonical, original, var_tok)
        else:
            kind = "lit"
            canonical = trimmed
            key = (kind, canonical, original, None)

        choice_keys.append(key)

    # Unique by (kind, canonical, var_tok) to avoid duplicates within the same cycle
    seen = set()
    unique_keys = []
    for k in choice_keys:
        tup = (k[0], k[1], k[3])
        if tup not in seen:
            seen.add(tup)
            unique_keys.append(k)

    # If overflow disabled, cap count
    if not bracket_ctx.get("allow_overflow", True):
        count = min(count, len(unique_keys))

    # Shuffle a cycle of unique keys
    cycle = list(unique_keys)
    rng.shuffle(cycle)

    results = []
    produced = 0
    safety_iters = 0
    max_iters = max(32, count * 8)

    def resolve_choice(key_quad):
        kind, canonical, original, var_tok = key_quad
        if kind == "lit":
            # Each time the outer bracket chooses this literal, evaluate it freshly.
            # Derive a unique deterministic seed for *this* evaluation from the bracket-local RNG.
            # This ensures nested brackets re-roll *every time this choice is selected*.
            # Consume one RNG from bracket_seeded and use its getrandbits() as the seed for the inner eval.
            eval_rng_source = bracket_seeded.next_rng()
            eval_seed_val = eval_rng_source.getrandbits(64)
            eval_seeded = SeededRandom(eval_seed_val)

            return resolve_wildcards(
                original, eval_seeded, wildcard_dir,
                _resolved_vars=_resolved_vars,
                _depth=0,
                bracket_ctx=None,               # fresh deck context per evaluation
                bracket_overflow=True,
            )

        elif kind == "var":
            # Pure variable recall (e.g., __^x__) — sample from resolved vars for 'canonical' (var name)
            rng_local = rng
            candidates = _collect_candidates(_resolved_vars, canonical, origin_filter=None)
            if candidates:
                return rng_local.choice(candidates)
            else:
                # nothing to recall; empty string
                return ""

        else:  # kind == "file"
            wc_name = canonical  # file name (may be "")
            # If wc_name is empty, no real file; treat as empty
            if not wc_name:
                return ""

            # Draw from file deck (deck-aware)
            sub_rng = rng
            drawn = process_file_wildcard(wc_name, sub_rng, wildcard_dir, bracket_ctx=bracket_ctx)
            if not drawn:
                return ""

            # Resolve nested wildcards inside drawn value (share bracket_ctx to keep deck state)
            resolved_val = resolve_wildcards(
                drawn, bracket_seeded, wildcard_dir,
                _resolved_vars=_resolved_vars,
                _depth=0,
                bracket_ctx=bracket_ctx,
                bracket_overflow=bracket_ctx.get("allow_overflow", True),
            )

            # If var_tok present, attempt to assign into _resolved_vars[var_tok][wc_name]
            if var_tok:
                # Do not clobber existing assignment for this origin (preserve if present)
                _ensure_var_bucket(_resolved_vars, var_tok)
                bucket = _resolved_vars[var_tok]
                # Use the file name as origin key so recall like __fruit^a__ stores under bucket['a']['fruit']
                origin_key = wc_name
                if origin_key not in bucket:
                    bucket[origin_key] = resolved_val
                # If already present, we keep old value (do not overwrite)
            return resolved_val

    while produced < count and safety_iters < max_iters:
        safety_iters += 1

        if not cycle:
            if not bracket_ctx.get("allow_overflow", True):
                break
            cycle = list(unique_keys)
            rng.shuffle(cycle)

        key = cycle.pop(0)
        piece = resolve_choice(key)
        results.append(piece)
        produced += 1

    # Join results using the separator EXACTLY as the user specified (resolve any wildcards inside it)
    if results:
        joined = results[0]
        for item in results[1:]:
            sep_seed = rng.getrandbits(64)
            sep_seeded = SeededRandom(sep_seed)
            sep_resolved = resolve_wildcards(
                separator, sep_seeded, wildcard_dir,
                _resolved_vars=_resolved_vars,
                _depth=0,
                bracket_ctx=bracket_ctx,
                bracket_overflow=bracket_ctx.get("allow_overflow", True),
            )
            joined += sep_resolved + item
        return joined
    else:
        return ""

# ---------------------- Main resolver (iterative passes + final sweep) ------------

_VARNAME_RE = re.compile(r"[A-Za-z0-9_\-]+")

def _final_sweep_resolve(text: str,
                         seeded_rng: SeededRandom,
                         wildcard_dir: str,
                         _resolved_vars: dict,
                         _depth: int) -> str:
    """
    Final left-to-right pass that tries to resolve any remaining variable/wildcard tokens.
    This is executed once after the iterative passes to rescue __^var__ style tokens that
    could not be resolved earlier.
    """
    i = 0
    while True:
        m = FILE_PATTERN.search(text, i)
        if not m:
            break
        full_token = m.group(0)
        wc_name = m.group(1)
        var_tok = m.group(2)

        replacement = None

        if wc_name is None and var_tok:
            candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=None)
            if candidates:
                replacement = seeded_rng.next_rng().choice(candidates)
            else:
                # fallback: try to resolve a wildcard file named var_tok (i.e., __^var__ (if no variable resolved, then -> __var__))
                rng_for_this = seeded_rng.next_rng()
                generated = process_file_wildcard(var_tok, rng_for_this, wildcard_dir, bracket_ctx=None)
                if generated and (generated == full_token or generated.strip() == full_token.strip()) is False:
                    replacement = resolve_wildcards(generated, seeded_rng, wildcard_dir,
                                                   _depth=_depth + 1, _resolved_vars=_resolved_vars)
                else:
                    replacement = ""
        elif wc_name is not None and var_tok:
            if "*" in var_tok:
                candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=wc_name)
                if candidates:
                    replacement = seeded_rng.next_rng().choice(candidates)
                else:
                    replacement = ""
            else:
                bucket = _resolved_vars.get(var_tok, {})
                if wc_name in bucket:
                    replacement = bucket[wc_name]
                else:
                    rng_for_this = seeded_rng.next_rng()
                    generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=None)
                    if generated and (generated == full_token or generated.strip() == full_token.strip()) is False:
                        replacement = resolve_wildcards(
                            generated, seeded_rng, wildcard_dir,
                            _depth=_depth + 1, _resolved_vars=_resolved_vars
                        )
                        _ensure_var_bucket(_resolved_vars, var_tok)
                        _resolved_vars[var_tok][wc_name] = replacement
                    else:
                        replacement = ""
        else:
            rng_for_this = seeded_rng.next_rng()
            generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=None)
            if generated and (generated == full_token or generated.strip() == full_token.strip()) is False:
                replacement = resolve_wildcards(
                    generated, seeded_rng, wildcard_dir,
                    _depth=_depth + 1, _resolved_vars=_resolved_vars
                )
            else:
                replacement = ""

        text = text[:m.start()] + replacement + text[m.end():]
        i = m.start() + len(replacement)

    return text

def resolve_wildcards(text: str,
                      seeded_rng: SeededRandom,
                      wildcard_dir: str,
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
    if _depth > 80:
        return text

    if _resolved_vars is None:
        _resolved_vars = {}

    # preserve whitespace/newlines: only ensure adjacent wildcard tokens separated
    text = _space_adjacent_wildcards(text)

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
                    repl = process_bracket(
                        content,
                        seeded_rng,
                        wildcard_dir,
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
                            max_attempts = 12
                            attempt = 0
                            value_to_store = None
                            prev_set = set(chain_assigned_values)
                            last_try = None
                            while attempt < max_attempts:
                                attempt += 1
                                candidate = process_bracket(
                                    content, seeded_rng, wildcard_dir,
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

                        _ensure_var_bucket(_resolved_vars, var_name)
                        bucket = _resolved_vars[var_name]
                        origin_key = f"__bracket_{len(bucket)}"
                        bucket[origin_key] = value_to_store

                        chain_assigned_values.append(value_to_store)

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

                replacement = ""

                if wc_name is None and var_tok:
                    # pure variable recall __^var__
                    rng_local = seeded_rng.next_rng()
                    candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=None)
                    if candidates:
                        replacement = rng_local.choice(candidates)
                    else:
                        # fallback: try to resolve a wildcard file named var_tok (i.e., __var_tok__)
                        rng_for_this = seeded_rng.next_rng()
                        generated = process_file_wildcard(var_tok, rng_for_this, wildcard_dir, bracket_ctx=None)
                        if generated:
                            replacement = resolve_wildcards(
                                generated, seeded_rng, wildcard_dir,
                                _depth=_depth + 1, _resolved_vars=_resolved_vars,
                                bracket_ctx=None,
                                bracket_overflow=bracket_overflow
                            )
                        else:
                            replacement = None

                elif wc_name is not None and var_tok:
                    # __file^var__ or __name^var__  (assignment or origin-scoped recall)
                    if "*" in var_tok:
                        rng_local = seeded_rng.next_rng()
                        candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=wc_name)
                        if candidates:
                            replacement = rng_local.choice(candidates)
                        else:
                            replacement = None
                    else:
                        bucket = _resolved_vars.get(var_tok, {})
                        if wc_name in bucket:
                            replacement = bucket[wc_name]
                        else:
                            # generate once and store under var_tok[wildcard_name]
                            rng_for_this = seeded_rng.next_rng()
                            generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=bracket_ctx)
                            if not generated or generated == full_token or generated.strip() == full_token.strip():
                                replacement = None
                            else:
                                replacement = resolve_wildcards(
                                    generated, seeded_rng, wildcard_dir,
                                    _depth=_depth + 1, _resolved_vars=_resolved_vars,
                                    bracket_ctx=bracket_ctx,
                                    bracket_overflow=bracket_overflow
                                )
                                _ensure_var_bucket(_resolved_vars, var_tok)
                                # do not overwrite existing origin value if present
                                if wc_name not in _resolved_vars[var_tok]:
                                    _resolved_vars[var_tok][wc_name] = replacement

                else:
                    # plain wildcard: __name__
                    rng_for_this = seeded_rng.next_rng()
                    generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=bracket_ctx)
                    if not generated or generated == full_token or generated.strip() == full_token.strip():
                        replacement = None
                    else:
                        replacement = resolve_wildcards(
                            generated, seeded_rng, wildcard_dir,
                            _depth=_depth + 1, _resolved_vars=_resolved_vars,
                            bracket_ctx=bracket_ctx,
                            bracket_overflow=bracket_overflow
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
    text = _final_sweep_resolve(text, seeded_rng, wildcard_dir, _resolved_vars, _depth)
    return text
