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
from collections import deque


BRACKET_PATTERN = re.compile(r"\{([^{}]+)\}")

# Wildcards + variables:
# - name may include letters/digits/_/-/* and '/'
# - name may start with one or more ./ or ../ prefixes for source-relative paths
# - optional ^var after the name (var may include trailing *)
# - also supports pure variable recall: __^var__
FILE_PATTERN = re.compile(
    r"__"
    r"((?:\.{1,2}/)*[a-zA-Z0-9_\-/*]+)?"  # optional name with optional ./.. prefix
    r"(?:\^([a-zA-Z0-9_\-\*]+))?"         # optional ^var
    r"__"
)

# Normalize spacing between adjacent wildcard-ish tokens (allow ^, *, and .)
ADJ_WC_PATTERN = re.compile(r"(__[a-zA-Z0-9_\-/*\^\*.]+__)(__[a-zA-Z0-9_\-/*\^\*.]+__)")

# marker used to separate adjacent wildcard tokens internally (removed at the end)
_ADJ_WC_MARKER = "<<ZWC>>"

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
    if not s:
        return s
    # Insert marker between the two matched wildcard tokens.
    return ADJ_WC_PATTERN.sub(r"\1" + _ADJ_WC_MARKER + r"\2", s)

# ---------------------- Wildcard blocking helpers -------------------------

# Regex to capture a backslash-escaped wildcard token: \__name__ or \__name^var__
_ESC_WC_RE = re.compile(r'\\(__[A-Za-z0-9_\-/*.]+(?:\^[A-Za-z0-9_\-\*]+)?__)')

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

_WEIGHT_RE = re.compile(r'(?<!\\)%([0-9]*\.?[0-9]+)')

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

def _draw_text_from_file(filepath: str,
                         rng: random.Random,
                         bracket_ctx: dict | None) -> str:
    """Draw one line from a wildcard file. Honors per-bracket no-repeat deck if provided."""
    if bracket_ctx is None:
        return _read_weighted_line(filepath, rng)
    deck = _ensure_deck_for_file(bracket_ctx, filepath)
    picked = _deck_draw(deck, rng, allow_overflow=bool(bracket_ctx.get("allow_overflow", True)))
    return picked or ""


def _find_at_base(name: str,
                  base: str,
                  rng: random.Random) -> str | None:
    """
    Resolve a (possibly path/glob) wildcard name against a single base directory.
    Returns the absolute filepath on success, or None.
    Handles: 'a/b/c', 'a/b/*', 'a/b/prefix*', '*', 'prefix*', 'name'.
    """
    if not name or not os.path.isdir(base):
        return None

    if "/" in name:
        dir_part, last = name.rsplit("/", 1)
        dir_path = os.path.join(base, dir_part)
        if last == "" or last == "*" or last.endswith("*"):
            prefix = None if last in ("", "*") else last[:-1]
            return _choose_file_from_dir(dir_path, rng, prefix=prefix)
        filepath = os.path.join(dir_path, f"{last}.txt")
        return filepath if os.path.isfile(filepath) else None

    if name == "*":
        return _choose_file_from_dir(base, rng, prefix=None)
    if name.endswith("*"):
        return _choose_file_from_dir(base, rng, prefix=name[:-1])

    filepath = os.path.join(base, f"{name}.txt")
    return filepath if os.path.isfile(filepath) else None


def _bfs_find_wildcard(name: str, root: str) -> str | None:
    """
    Breadth-first search under `root` for a wildcard file.
      - Bare 'foo'      -> finds any 'foo.txt' anywhere in the tree.
      - Path 'a/b/foo'  -> finds 'a/b/foo.txt' nested at any depth.
    Returns the absolute filepath, or None. Caller is responsible for
    skipping glob names (the meaning would be ambiguous).
    """
    if not name or not os.path.isdir(root):
        return None
    if "*" in name:
        return None

    target_rel = name.replace("/", os.sep) + ".txt"
    queue = deque([root])
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

        candidate = os.path.join(current, target_rel)
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


def process_file_wildcard(name: str,
                          rng: random.Random,
                          wildcard_dir: str,
                          source_file: str | None,
                          bracket_ctx: dict | None = None) -> tuple[str, str | None]:
    """
    Resolve a wildcard token like __name__, __./name__, __../name__, or __a/b/c__.

    Lookup chain (for unprefixed names):
      1. The source file's directory (if known) -- so 'cave' next to 'random.txt'
         finds 'cave.txt' in the same folder.
      2. The wildcard root (primary_dir; DEFAULT_WILDCARD_ROOT is also tried as a
         final fallback when primary_dir was overridden).
      3. BFS through the wildcard tree, looking for `name.txt` (or for path-form
         names like 'a/b/c', the relative subpath 'a/b/c.txt' nested anywhere).

    Prefix semantics:
      - './name'  - explicit; only the source directory is tried, no BFS.
      - '../name' - explicit; only the parent of the source directory is tried,
                    no BFS. Multiple ../ may be chained.
      - 'a/b/c'   - path-form; resolved using the full chain above. Inside
                    'Pokemon/', '__Generation4/weavile__' finds
                    'Pokemon/Generation4/weavile.txt' at step 1 — relative
                    paths behave the way they do in any other filesystem.
                    The path is also used as the search target for BFS, so
                    '__Pokemon/Generation4/weavile__' can be written from
                    anywhere and BFS will find the matching subpath.

    Glob patterns (containing '*') always skip BFS; with no concrete name to
    match, a tree-wide search would be ambiguous.

    Returns:
        (drawn_text, resolved_filepath)
        - drawn_text:        the line drawn from the resolved file, or "" if
                              nothing matched.
        - resolved_filepath: absolute path of the file actually read, or None
                              if no file was read. Callers should pass this
                              back as `source_file` when recursively resolving
                              the drawn line, so nested wildcards inside it
                              resolve relative to where they came from.
    """
    if not name:
        return "", None

    primary_dir = wildcard_dir or DEFAULT_WILDCARD_ROOT

    # Source directory (where the current text was drawn from, if known)
    source_dir = None
    if source_file:
        try:
            sf_abs = os.path.abspath(source_file)
            if os.path.isfile(sf_abs):
                source_dir = os.path.dirname(sf_abs)
        except Exception:
            source_dir = None

    # --- Parse leading ./ and ../ chains ---
    explicit_relative = False
    explicit_base = None
    walking = name
    while True:
        if walking.startswith("./"):
            walking = walking[2:]
            explicit_relative = True
            if explicit_base is None:
                explicit_base = source_dir or primary_dir
        elif walking.startswith("../"):
            walking = walking[3:]
            explicit_relative = True
            base = explicit_base if explicit_base is not None else (source_dir or primary_dir)
            explicit_base = os.path.dirname(base) if base else primary_dir
        else:
            break

    name = walking.strip("/")
    if not name:
        return "", None

    has_glob = "*" in name

    # --- Build the list of base directories to try, in priority order ---
    search_bases: list[str] = []

    if explicit_relative:
        # Explicit ./ or ../ : only try the resolved location.
        if explicit_base:
            search_bases.append(explicit_base)
    else:
        # Implicit chain:
        #   - Bare names look in the source dir first (e.g. 'cave' next to 'random.txt').
        #   - Path-form names ALSO look in the source dir first (e.g. 'Generation4/weavile'
        #     from inside 'Pokemon/' resolves to 'Pokemon/Generation4/weavile.txt'
        #     directly, without walking the whole tree).
        if source_dir is not None:
            search_bases.append(source_dir)
        search_bases.append(primary_dir)
        if os.path.abspath(primary_dir) != os.path.abspath(DEFAULT_WILDCARD_ROOT):
            search_bases.append(DEFAULT_WILDCARD_ROOT)

    # De-duplicate while preserving order
    seen = set()
    deduped = []
    for b in search_bases:
        if not b:
            continue
        try:
            key = os.path.abspath(b)
        except Exception:
            key = b
        if key not in seen:
            seen.add(key)
            deduped.append(b)
    search_bases = deduped

    # --- Steps 1 & 2: direct resolution at each base ---
    for base in search_bases:
        fp = _find_at_base(name, base, rng)
        if fp:
            return _draw_text_from_file(fp, rng, bracket_ctx), fp

    # --- Step 3: BFS fallback ---
    # Only for implicit lookups, and only for non-glob names.
    if not explicit_relative and not has_glob:
        bfs_roots = [primary_dir]
        if os.path.abspath(primary_dir) != os.path.abspath(DEFAULT_WILDCARD_ROOT):
            bfs_roots.append(DEFAULT_WILDCARD_ROOT)
        for root in bfs_roots:
            bfs_fp = _bfs_find_wildcard(name, root)
            if bfs_fp:
                return _draw_text_from_file(bfs_fp, rng, bracket_ctx), bfs_fp

    # --- Step 4: nothing found (silent empty, matching legacy behavior) ---
    return "", None

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

# ---------------------- Bracket processing ----------------------------------

def process_bracket(content: str,
                    source_file: str,
                    seeded_rng: SeededRandom,
                    wildcard_dir: str,
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
        else:
            idx1, token = separators[0]
            idx2, _ = separators[1]
            count_part = content[:idx1]
            raw_separator = content[idx1 + 2:idx2]
            choices_str = content[idx2 + 2:]

            try:
                separator = raw_separator.encode("utf-8").decode("unicode_escape")
            except Exception:
                separator = raw_separator

        if count_part.strip() == "*":
            exhaust_all = True
        elif "-" in count_part:
            lo, hi = map(int, count_part.split("-", 1))
            count = seeded_rng.next_rng().randint(lo, hi)
        else:
            try:
                count = int(count_part)
            except Exception:
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
        results = []

        for key in unique_keys:
            kind, canonical, original, var_tok = key

            if kind == "var":
                # Pull every assigned value for this variable
                vals = _collect_candidates(_resolved_vars, canonical, origin_filter=None)
                results.extend(vals)
            else:
                eval_seed = seeded_rng.next_rng().getrandbits(64)
                eval_rng = SeededRandom(eval_seed)
                resolved = resolve_wildcards(
                    original, source_file, eval_rng, wildcard_dir,
                    _resolved_vars=_resolved_vars,
                    bracket_ctx=bracket_ctx if kind == "file" else None,
                    bracket_overflow=True
                )
                if resolved != "":
                    results.append(resolved)

        # Join with separator
        if results:
            joined = results[0]
            for item in results[1:]:
                sep_seed = seeded_rng.next_rng().getrandbits(64)
                sep_rng = SeededRandom(sep_seed)
                sep_resolved = resolve_wildcards(
                    separator, source_file, sep_rng, wildcard_dir,
                    _resolved_vars=_resolved_vars,
                    bracket_ctx=bracket_ctx,
                    bracket_overflow=bracket_ctx["allow_overflow"]
                )
                joined += sep_resolved + item
            return joined
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
        eval_rng = SeededRandom(eval_seed)

        if kind == "lit":
            return resolve_wildcards(
                original, source_file, eval_rng, wildcard_dir,
                _resolved_vars=_resolved_vars,
                bracket_ctx=None,
                bracket_overflow=True
            )

        if kind == "var":
            vals = _collect_candidates(_resolved_vars, canonical, None)
            return rng.choice(vals) if vals else ""

        drawn, drawn_fp = process_file_wildcard(canonical, rng, wildcard_dir, source_file, bracket_ctx)
        if not drawn:
            return ""

        resolved = resolve_wildcards(
            drawn, drawn_fp, eval_rng, wildcard_dir,
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

    joined = results[0]
    for item in results[1:]:
        sep_seed = seeded_rng.next_rng().getrandbits(64)
        sep_rng = SeededRandom(sep_seed)
        sep_resolved = resolve_wildcards(
            separator, source_file, sep_rng, wildcard_dir,
            _resolved_vars=_resolved_vars,
            bracket_ctx=bracket_ctx,
            bracket_overflow=bracket_ctx["allow_overflow"]
        )
        joined += sep_resolved + item

    return joined


# ---------------------- Main resolver (iterative passes + final sweep) ------------

_VARNAME_RE = re.compile(r"[A-Za-z0-9_\-]+")

def _final_sweep_resolve(text: str,
                         source_file: str,
                         seeded_rng: SeededRandom,
                         wildcard_dir: str,
                         _resolved_vars: dict,
                         _depth: int,
                         escaped_map: dict | None = None) -> str:
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
                generated, generated_fp = process_file_wildcard(var_tok, rng_for_this, wildcard_dir, source_file, bracket_ctx=None)
                if generated and (generated == full_token or generated.strip() == full_token.strip()) is False:
                    replacement = resolve_wildcards(generated, generated_fp, seeded_rng, wildcard_dir,
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
                    generated, generated_fp = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, source_file, bracket_ctx=None)
                    if generated and (generated == full_token or generated.strip() == full_token.strip()) is False:
                        replacement = resolve_wildcards(
                            generated, generated_fp,  seeded_rng, wildcard_dir,
                            _depth=_depth + 1, _resolved_vars=_resolved_vars
                        )
                        _ensure_var_bucket(_resolved_vars, var_tok)
                        # restore any protected escaped wildcards before storing into context
                        to_store = _restore_escaped_wildcards(replacement, escaped_map or {})
                        _resolved_vars[var_tok][wc_name] = to_store.replace(_ADJ_WC_MARKER, "")
                    else:
                        replacement = ""
        else:
            rng_for_this = seeded_rng.next_rng()
            generated, generated_fp = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, source_file, bracket_ctx=None)
            if generated and (generated == full_token or generated.strip() == full_token.strip()) is False:
                replacement = resolve_wildcards(
                    generated, generated_fp, seeded_rng, wildcard_dir,
                    _depth=_depth + 1, _resolved_vars=_resolved_vars
                )
            else:
                replacement = ""

        text = text[:m.start()] + replacement + text[m.end():]
        i = m.start() + len(replacement)

    return text

def resolve_wildcards(text: str,
                      source_file: str | None,
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
                    repl = process_bracket(
                        content,
                        source_file,
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
                                    content, source_file,
                                    seeded_rng,
                                    wildcard_dir,
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
                        generated, generated_fp = process_file_wildcard(var_tok, rng_for_this, wildcard_dir, source_file, bracket_ctx=None)
                        if generated:
                            replacement = resolve_wildcards(
                                generated,
                                generated_fp,
                                seeded_rng,
                                wildcard_dir,
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
                            generated, generated_fp = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, source_file, bracket_ctx=bracket_ctx)
                            if not generated or generated == full_token or generated.strip() == full_token.strip():
                                replacement = None
                            else:
                                replacement = resolve_wildcards(
                                    generated, generated_fp,
                                    seeded_rng,
                                    wildcard_dir,
                                    _depth=_depth + 1, _resolved_vars=_resolved_vars,
                                    bracket_ctx=bracket_ctx,
                                    bracket_overflow=bracket_overflow
                                )
                                _ensure_var_bucket(_resolved_vars, var_tok)
                                # do not overwrite existing origin value if present
                                if wc_name not in _resolved_vars[var_tok]:
                                    to_store = _restore_escaped_wildcards(replacement, _escaped_wildcard_map or {})
                                    _resolved_vars[var_tok][wc_name] = to_store

                else:
                    # plain wildcard: __name__
                    rng_for_this = seeded_rng.next_rng()
                    generated, generated_fp = process_file_wildcard(wc_name, rng_for_this, wildcard_dir, source_file, bracket_ctx=bracket_ctx)
                    if not generated or generated == full_token or generated.strip() == full_token.strip():
                        replacement = None
                    else:
                        replacement = resolve_wildcards(
                            generated, generated_fp,
                            seeded_rng,
                            wildcard_dir,
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
    text = _final_sweep_resolve(
        text, source_file, seeded_rng, wildcard_dir, _resolved_vars, _depth,
        escaped_map=_escaped_wildcard_map
    )
    # RESTORE any protected escaped wildcard placeholders back to literal text
    text = _restore_escaped_wildcards(text, _escaped_wildcard_map)
    text = text.replace(_ADJ_WC_MARKER, "")
    return text