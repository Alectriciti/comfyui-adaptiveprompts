"""
Adaptive Prompts: generator
The brain of parsing bracket/file wildcards
Designed by Alectriciti

Changes:
- Per-bracket "deck" context that enforces no-repeat draws from wildcard files
  until their options are exhausted (then repeats allowed only if overflow=True).
- Top-level bracket choice cycle: each choice in a bracket (literal or wildcard)
  is used once per cycle, in random order. Additional items are produced only if
  bracket_overflow=True (then we start another cycle).
- Weighted lines still work (%w% syntax). Within a deck, choices are drawn
  WITHOUT replacement using the current remaining weights. When a deck empties:
    * overflow=True  -> deck is refilled (repeats now allowed)
    * overflow=False -> no more draws from that wildcard in this bracket
- Bracket deck context is shared across all nested resolutions triggered by the
  SAME bracket (so nested { … } and __file__ inside it respect the same cards).
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
        """
        Returns the next random float in [0.0, 1.0).
        """
        rng = self.next_rng()
        return rng.random()

    def uniform(self, a: float, b: float) -> float:
        """
        Returns a random float N such that a <= N <= b using the current seed.
        Each call advances the seed to ensure deterministic but unique output.
        """
        rng = self.next_rng()
        return rng.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        """
        Returns a random integer N such that a <= N <= b.
        """
        rng = self.next_rng()
        return rng.randint(a, b)

    def choice(self, seq):
        """
        Returns a random element from a non-empty sequence.
        """
        rng = self.next_rng()
        return rng.choice(seq)

# ------------------------- Quick taggers/helpers ----------------------------

def is_file_wildcard(choice: str) -> bool:
    return bool(FILE_PATTERN.fullmatch(choice.strip()))

def _space_adjacent_wildcards(s: str) -> str:
    return ADJ_WC_PATTERN.sub(r"\1 \2", s)

# ---------------------- Top-level split helpers ------------------------------

def _find_top_level_dollars(s: str) -> list[int]:
    """
    Return indices where top-level '$$' occurs
    """
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
    Returns list of segments.
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
            part = "".join(buf)
            parts.append(part)
            buf = []
        else:
            buf.append(c)
        i += 1
    last = "".join(buf)
    if last:
        parts.append(last)
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
        # Remove inline comments after unescaped '#'
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
        # fallback to uniform
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
    """
    Legacy single-draw helper (used when no bracket context is active).
    """
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
    file patterns supported:
      __fruit__                  -> wildcards/fruit.txt
      __fruit*__                 -> any root file starting with 'fruit'
      __*__                      -> any root file
      __dir/file__               -> wildcards/dir/file.txt
      __dir/*__                  -> random file inside wildcards/dir/
      __dir/prefix*__            -> file in dir with name starting with prefix

    If 'bracket_ctx' is provided, draws are done WITHOUT replacement from a deck
    (per file) for the lifetime of this bracket.
    """
    if not name:
        return ""  # e.g., pure variable recall __^var__

    name = name.strip("/")

    def draw_from_filepath(filepath: str) -> str:
        if not filepath or not os.path.exists(filepath):
            return ""
        if bracket_ctx is None:
            # Normal single weighted draw (no deck/no-repeat)
            return _read_weighted_line(filepath, rng)
        else:
            # Decked (no-repeat in this bracket)
            deck = _ensure_deck_for_file(bracket_ctx, filepath)
            sub_rng = rng  # use same rng object here
            picked = _deck_draw(deck, sub_rng, allow_overflow=bool(bracket_ctx.get("allow_overflow", True)))
            return picked or ""

    if "/" in name:
        dir_part, last = name.rsplit("/", 1)
        dir_path = os.path.join(wildcard_dir, dir_part)

        if last == "" or last == "*" or last.endswith("*"):
            prefix = None if last in ("", "*") else last[:-1]
            chosen = _choose_file_from_dir(dir_path, rng, prefix=prefix)
            return draw_from_filepath(chosen) if chosen else ""

        filepath = os.path.join(dir_path, f"{last}.txt")
        return draw_from_filepath(filepath)

    # Root-level cases
    if name == "*":
        chosen = _choose_file_from_dir(wildcard_dir, rng, prefix=None)
        return draw_from_filepath(chosen) if chosen else ""

    if name.endswith("*"):
        prefix = name[:-1]
        chosen = _choose_file_from_dir(wildcard_dir, rng, prefix=prefix)
        return draw_from_filepath(chosen) if chosen else ""

    filepath = os.path.join(wildcard_dir, f"{name}.txt")
    return draw_from_filepath(filepath)

def weighted_choice(options: list[str], rng: random.Random) -> str:
    # kept for API completeness (used in legacy paths)
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
    spans = []  # list of (start, end, depth)
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

    # look for spans where a nested bracket is inside the top-level separator region
    candidates = []
    for s, e, depth in spans:
        content = text[s+1:e]
        dollar_idxs = _find_top_level_dollars(content)
        if len(dollar_idxs) >= 2:
            idx1 = dollar_idxs[0]
            idx2 = dollar_idxs[1]
            # find any nested span whose local start lies inside content[idx1+2:idx2]
            for ns, ne, nd in spans:
                if ns > s and ne < e:
                    nested_local_start = ns - (s + 1)
                    if nested_local_start >= idx1 + 2 and nested_local_start < idx2:
                        candidates.append((s, e, depth))
                        break

    if candidates:
        candidates.sort(key=lambda x: x[0])  # earliest outer bracket first
        return (candidates[0][0], candidates[0][1])

    # fallback: innermost span
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

    # Ensure/seed a bracket context
    if bracket_ctx is None:
        bracket_ctx = {"allow_overflow": bool(bracket_overflow), "decks": {}}

    # Find top-level $$ markers (ignoring nested brackets)
    dollar_idxs = _find_top_level_dollars(content)

    if not dollar_idxs:
        # No count/separator notation, entire content is choices
        choices_str = content
    elif len(dollar_idxs) == 1:
        # format: count$$choices
        idx1 = dollar_idxs[0]
        count_part = content[:idx1].strip()
        choices_str = content[idx1 + 2 :]
        # parse count
        if "-" in count_part:
            low, high = map(int, count_part.split("-", 1))
            count = seeded_rng.next_rng().randint(low, high)
        else:
            count = int(count_part)
    else:
        # format: count$$separator$$choices
        idx1 = dollar_idxs[0]
        idx2 = dollar_idxs[1]
        count_part = content[:idx1].strip()
        raw_separator = content[idx1 + 2 : idx2]
        choices_str = content[idx2 + 2 :]

        # parse count
        if "-" in count_part:
            low, high = map(int, count_part.split("-", 1))
            count = seeded_rng.next_rng().randint(low, high)
        else:
            count = int(count_part)

        # decode escape sequences like '\n'
        try:
            separator = raw_separator.encode("utf-8").decode("unicode_escape")
        except Exception:
            separator = raw_separator

    # Split choices by top-level pipes (ignore nested '|'), and preserve a single-space choice " " as a valid option.
    raw_choices = []
    for c in _split_top_level_pipes(choices_str):
        if c == " ":
            # allow exactly one-space to survive as a choice
            raw_choices.append(c)
        else:
            # otherwise require non-empty after stripping
            if c.strip():
                raw_choices.append(c)
    rng = seeded_rng.next_rng()

    # Canonicalize choice keys so each top-level choice is used once per cycle
    # A key is (kind, canonical, original_string)
    choice_keys = []
    for c in raw_choices:
        # preserve a single-space choice (don't strip it to empty string)
        if c == " ":
            c_stripped = " "
        else:
            c_stripped = c.strip()

        if is_file_wildcard(c_stripped):
            m = FILE_PATTERN.fullmatch(c_stripped)
            wc_name = (m.group(1) or "").strip()
            key = ("file", wc_name, c_stripped)
        else:
            key = ("lit", c_stripped, c_stripped)
        choice_keys.append(key)


    # Unique by key (kind+canonical), then we will shuffle per cycle
    # Keep insertion order first, then shuffle cycle each time for randomness.
    seen = set()
    unique_keys = []
    for k in choice_keys:
        tup = (k[0], k[1])  # (kind, canonical)
        if tup not in seen:
            seen.add(tup)
            unique_keys.append(k)

    # If overflow is disabled, the max outputs equals number of unique top-level choices
    if not bracket_ctx.get("allow_overflow", True):
        count = min(count, len(unique_keys))

    # Start a first cycle in random order
    cycle = list(unique_keys)
    rng.shuffle(cycle)

    results = []
    produced = 0
    safety_iters = 0
    max_iters = max(32, count * 8)

    def resolve_choice(key_triplet):
        kind, canonical, original = key_triplet
        if kind == "lit":
            # Resolve nested wildcards/brackets inside the literal choice using SAME bracket_ctx
            return resolve_wildcards(
                original, seeded_rng, wildcard_dir,
                _resolved_vars=_resolved_vars, _depth=0,
                bracket_ctx=bracket_ctx,
                bracket_overflow=bracket_ctx.get("allow_overflow", True),
            )
        else:
            # FILE wildcard: resolve using deck-aware process_file_wildcard
            m = FILE_PATTERN.fullmatch(original)
            wc_name = (m.group(1) or "").strip()
            sub_rng = seeded_rng.next_rng()
            # Draw one line from the file (no-repeat in this bracket)
            val = process_file_wildcard(wc_name, sub_rng, wildcard_dir, bracket_ctx=bracket_ctx)
            if not val:
                return ""
            # The drawn value might itself contain nested {...} or __...__; resolve them
            return resolve_wildcards(
                val, seeded_rng, wildcard_dir,
                _resolved_vars=_resolved_vars, _depth=0,
                bracket_ctx=bracket_ctx,
                bracket_overflow=bracket_ctx.get("allow_overflow", True),
            )

    while produced < count and safety_iters < max_iters:
        safety_iters += 1

        if not cycle:
            # start a new cycle only if overflow is allowed
            if not bracket_ctx.get("allow_overflow", True):
                break
            cycle = list(unique_keys)
            rng.shuffle(cycle)

        key = cycle.pop(0)
        piece = resolve_choice(key)

        # Accept the piece (including empty string) as a produced slot.
        results.append(piece)
        produced += 1

    # Join results using separator — evaluate separator freshly for each join
    # (separator may itself contain nested wildcards/brackets/vars), using SAME bracket_ctx
    if results:
        joined = results[0]
        for item in results[1:]:
            rng_for_sep = seeded_rng.next_rng()
            sep_seed = rng_for_sep.getrandbits(64)
            sep_seeded = SeededRandom(sep_seed)
            sep_resolved = resolve_wildcards(
                separator, sep_seeded, wildcard_dir,
                _resolved_vars=_resolved_vars, _depth=0,
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
    indent = "  " * _depth
    i = 0
    while True:
        m = FILE_PATTERN.search(text, i)
        if not m:
            break
        full_token = m.group(0)
        wc_name = m.group(1)   # may be None for pure var recall
        var_tok = m.group(2)   # may be None or include '*'

        replacement = None

        if wc_name is None and var_tok:
            # pure variable recall: __^var__ / __^a*__ / __^*__
            candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=None)
            if candidates:
                replacement = seeded_rng.next_rng().choice(candidates)
            else:
                replacement = ""  # remove unrecoverable var

        elif wc_name is not None and var_tok:
            # origin-scoped recall or assignment attempt
            if "*" in var_tok:
                candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=wc_name)
                if candidates:
                    replacement = seeded_rng.next_rng().choice(candidates)
                else:
                    replacement = ""  # nothing to recall
            else:
                bucket = _resolved_vars.get(var_tok, {})
                if wc_name in bucket:
                    replacement = bucket[wc_name]
                else:
                    # Attempt to assign once from the wildcard file as a last resort
                    rng_for_this = seeded_rng.next_rng()
                    generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=None)
                    if generated and generated.strip() != full_token:
                        replacement = resolve_wildcards(generated, seeded_rng, wildcard_dir,
                                                       _depth=_depth + 1, _resolved_vars=_resolved_vars)
                        _ensure_var_bucket(_resolved_vars, var_tok)
                        _resolved_vars[var_tok][wc_name] = replacement
                    else:
                        replacement = ""  # remove if we cannot generate

        else:
            # plain wildcard leftover: attempt to generate once
            rng_for_this = seeded_rng.next_rng()
            generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=None)
            if generated and generated.strip() != full_token:
                replacement = resolve_wildcards(generated, seeded_rng, wildcard_dir,
                                               _depth=_depth + 1, _resolved_vars=_resolved_vars)
            else:
                replacement = ""

        # Apply replacement and continue
        text = text[:m.start()] + replacement + text[m.end():]
        i = m.start() + len(replacement)

    #print(f"{indent}[final sweep] result: {repr(text)}")
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
    indent = "  " * _depth
    #print(f"{indent}Resolving (depth {_depth}) start: {repr(text)}")

    if _depth > 80:
        print(f"{indent}⚠️ Max recursion depth reached; returning text as-is.")
        return text

    if _resolved_vars is None:
        _resolved_vars = {}

    # ensure adjacent wildcards spaced
    text = _space_adjacent_wildcards(text)

    # placeholders for unresolved tokens during a single pass
    placeholder_counter = 0
    placeholders = {}  # placeholder -> original token

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

                # decide which comes first
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

                    # bracket variable chaining logic (unchanged)
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
                        working = working[:br_start] + repl + working[replace_end:]
                    else:
                        working = working[:br_start] + repl + working[br_end + 1:]

                    working = _space_adjacent_wildcards(working)
                    continue

                # handle file/wildcard token
                full_token = m_file.group(0)
                wc_name = m_file.group(1)   # may be None for pure var recall
                var_tok = m_file.group(2)   # may be None or include '*'

                replacement = ""

                if wc_name is None and var_tok:
                    # Pure variable recall e.g. __^alpha__
                    rng_local = seeded_rng.next_rng()
                    candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=None)
                    if candidates:
                        replacement = rng_local.choice(candidates)
                    else:
                        replacement = None  # unresolved

                elif wc_name is not None and var_tok:
                    # assignment or origin-scoped recall: __origin^var__ or __origin^*__
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
                            rng_for_this = seeded_rng.next_rng()
                            generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=bracket_ctx)
                            if not generated or generated.strip() == full_token:
                                replacement = None
                            else:
                                replacement = resolve_wildcards(
                                    generated, seeded_rng, wildcard_dir,
                                    _depth=_depth + 1, _resolved_vars=_resolved_vars,
                                    bracket_ctx=bracket_ctx,
                                    bracket_overflow=bracket_overflow
                                )
                                _ensure_var_bucket(_resolved_vars, var_tok)
                                _resolved_vars[var_tok][wc_name] = replacement

                else:
                    # plain wildcard: __name__
                    rng_for_this = seeded_rng.next_rng()
                    generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, bracket_ctx=bracket_ctx)
                    if not generated or generated.strip() == full_token:
                        replacement = None
                    else:
                        replacement = resolve_wildcards(
                            generated, seeded_rng, wildcard_dir,
                            _depth=_depth + 1, _resolved_vars=_resolved_vars,
                            bracket_ctx=bracket_ctx,
                            bracket_overflow=bracket_overflow
                        )

                # apply logic: if replacement is None -> unresolved this pass
                if replacement is None:
                    ph = next_placeholder()
                    placeholders[ph] = full_token
                    working = working[:m_file.start()] + ph + working[m_file.end():]
                    #print(f"{indent}  [pass] placeholdering unresolved token {full_token!r} -> {ph!r}")
                else:
                    working = working[:m_file.start()] + replacement + working[m_file.end():]
                    changed = True
                    working = _space_adjacent_wildcards(working)
                    #print(f"{indent}  [pass] replaced {full_token!r} -> {replacement!r}")

            return working

        # run single pass
        new_text = _single_pass(text)

        # restore placeholders to original tokens for next pass attempts
        if placeholders:
            for ph, orig in placeholders.items():
                new_text = new_text.replace(ph, orig)
            placeholders = {}
            placeholder_counter = 0

        #print(f"{indent}After pass {pass_no}: {repr(new_text)} (changed={changed})")

        if not changed:
            text = new_text
            break

        text = new_text
        text = _space_adjacent_wildcards(text)

    else:
        print(f"{indent}⚠️ Adaptive Prompts reached max passes ({max_passes}) reached; returning current text.")

    # Final sweep (no bracket context here on purpose)
    text = _final_sweep_resolve(text, seeded_rng, wildcard_dir, _resolved_vars, _depth)

    #print(f"{indent}Resolving (depth {_depth}) result: {repr(text)}")
    return text
