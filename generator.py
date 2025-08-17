import re
import os
import random
import sys

BRACKET_PATTERN = re.compile(r"\{([^{}]+)\}")

# Wildcards + variables:
# - name may include letters/digits/_/-/* and '/'
# - optional ^var after the name (var may include trailing *)
# - also supports pure variable recall: __^var__
FILE_PATTERN = re.compile(r"__(?:([a-zA-Z0-9_\-/*]+?))?(?:\^([a-zA-Z0-9_\-\*]+))?__")

# Normalize spacing between adjacent wildcard-ish tokens (allow ^ and *)
ADJ_WC_PATTERN = re.compile(r"(__[a-zA-Z0-9_\-/*\^\*]+__)(__[a-zA-Z0-9_\-/*\^\*]+__)")

class SeededRandom:
    def __init__(self, base_seed: int):
        self.seed = base_seed

    def next_rng(self) -> random.Random:
        # Each call advances the seed and returns a new Random instance
        self.seed += 1
        return random.Random(self.seed)

def is_file_wildcard(choice: str) -> bool:
    return bool(FILE_PATTERN.fullmatch(choice.strip()))

# ---------------------- Top-level split helpers ------------------------------

def _find_top_level_dollars(s: str) -> list[int]:
    """
    Return indices where top-level '$$' occurs (i.e., not inside nested {...} groups).
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
    Returns list of segments (trimmed).
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

# ---------------------- Bracket processing ----------------------------------

def process_bracket(content: str,
                    seeded_rng: SeededRandom,
                    wildcard_dir: str,
                    _resolved_vars=None) -> str:
    """
    Handles bracket syntax with:
      - count and optional custom separator using top-level $$ markers
      - choices split at top-level '|'
      - nested bracket/wildcard resolution for both choices and separators
    """
    # Default
    count = 1
    separator = ", "
    choices_str = content

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

    # Split choices by top-level pipes (ignore nested '|')
    choices = [c for c in _split_top_level_pipes(choices_str) if c.strip()]
    rng = seeded_rng.next_rng()

    # Separate file-wildcard-styled choices from plain ones
    file_wildcards = [c for c in choices if is_file_wildcard(c)]
    non_file_wildcards = [c for c in choices if not is_file_wildcard(c)]

    results = []
    used_non_file = set()

    # Build results (allow nested resolution)
    while len(results) < count:
        if not non_file_wildcards:
            # choose from file wildcards only
            pick = rng.choice(file_wildcards) if file_wildcards else None
            if pick is None:
                break
        else:
            available_non_file = [c for c in non_file_wildcards if c not in used_non_file]
            if available_non_file:
                # allow mixing file wildcards + available non-file choices
                pool = file_wildcards + available_non_file if file_wildcards else available_non_file
                pick = rng.choice(pool)
                if not is_file_wildcard(pick):
                    used_non_file.add(pick)
            else:
                # all non-file used — fallback to file wildcards if present
                if file_wildcards:
                    pick = rng.choice(file_wildcards)
                else:
                    # nothing usable; reset and retry
                    used_non_file.clear()
                    continue

        # Resolve the chosen pick (it might contain nested brackets/wildcards/vars)
        pick_resolved = resolve_wildcards(pick, seeded_rng, wildcard_dir, _resolved_vars=_resolved_vars)
        results.append(pick_resolved)

    # Join results using separator — evaluate separator freshly for each join
    # (separator may itself contain nested wildcards/brackets/vars)
    if results:
        joined = results[0]
        for item in results[1:]:
            # Advance the main RNG and derive a per-join seed for the separator,
            # so each separator evaluation is deterministic but independent.
            rng_for_sep = seeded_rng.next_rng()
            sep_seed = rng_for_sep.getrandbits(64)
            sep_seeded = SeededRandom(sep_seed)

            sep_resolved = resolve_wildcards(separator, sep_seeded, wildcard_dir, _resolved_vars=_resolved_vars)
            joined += sep_resolved + item
        return joined
    else:
        return ""

# ---------------------- File I/O / wildcard selection -----------------------

def _read_weighted_line(filepath: str, rng: random.Random) -> str:
    options = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                line = re.split(r'(?<!\\)#', line)[0].strip()
                if line:
                    options.append(line)
    except OSError:
        return ""
    if not options:
        return ""
    return weighted_choice(options, rng)

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
                          wildcard_dir: str) -> str:
    """
    file patterns supported:
      __fruit__                  -> wildcards/fruit.txt
      __fruit*__                 -> any root file starting with 'fruit'
      __*__                      -> any root file
      __dir/file__               -> wildcards/dir/file.txt
      __dir/*__                  -> random file inside wildcards/dir/
      __dir/prefix*__            -> file in dir with name starting with prefix
    """
    if not name:
        return ""  # e.g., pure variable recall __^var__

    name = name.strip("/")

    if "/" in name:
        dir_part, last = name.rsplit("/", 1)
        dir_path = os.path.join(wildcard_dir, dir_part)

        if last == "":
            chosen = _choose_file_from_dir(dir_path, rng, prefix=None)
            return _read_weighted_line(chosen, rng) if chosen else ""

        if last == "*":
            chosen = _choose_file_from_dir(dir_path, rng, prefix=None)
            return _read_weighted_line(chosen, rng) if chosen else ""

        if last.endswith("*"):
            prefix = last[:-1]
            chosen = _choose_file_from_dir(dir_path, rng, prefix=prefix)
            return _read_weighted_line(chosen, rng) if chosen else ""

        filepath = os.path.join(dir_path, f"{last}.txt")
        return _read_weighted_line(filepath, rng) if os.path.exists(filepath) else ""

    # Root-level cases
    if name == "*":
        chosen = _choose_file_from_dir(wildcard_dir, rng, prefix=None)
        return _read_weighted_line(chosen, rng) if chosen else ""

    if name.endswith("*"):
        prefix = name[:-1]
        chosen = _choose_file_from_dir(wildcard_dir, rng, prefix=prefix)
        return _read_weighted_line(chosen, rng) if chosen else ""

    filepath = os.path.join(wildcard_dir, f"{name}.txt")
    return _read_weighted_line(filepath, rng) if os.path.exists(filepath) else ""

def weighted_choice(options: list[str], rng: random.Random) -> str:
    lines, weights = [], []
    for option in options:
        option = option.strip()
        if not option:
            continue
        m = re.search(r'(?<!\\)%([0-9]*\.?[0-9]+)%', option)
        if m:
            weight = float(m.group(1))
            option = (option[:m.start()] + option[m.end():]).strip()
        else:
            weight = 1.0
        option = option.replace(r'\%', '%')
        if option:
            lines.append(option)
            weights.append(weight)
    if not lines:
        return ""
    return rng.choices(lines, weights=weights, k=1)[0]

# ---------------------- Variable helpers ------------------------------------

def _space_adjacent_wildcards(s: str) -> str:
    return ADJ_WC_PATTERN.sub(r"\1 \2", s)

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
                # e.g., __character^*__ -> pick among values stored under origin 'character'
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
                    generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir)
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
            generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir)
            if generated and generated.strip() != full_token:
                replacement = resolve_wildcards(generated, seeded_rng, wildcard_dir,
                                               _depth=_depth + 1, _resolved_vars=_resolved_vars)
            else:
                replacement = ""

        # Apply replacement and continue
        text = text[:m.start()] + replacement + text[m.end():]
        # advance index to after replacement to avoid infinite loop on same spot
        i = m.start() + len(replacement)

    print(f"{indent}[final sweep] result: {repr(text)}")
    return text

def resolve_wildcards(text: str,
                      seeded_rng: SeededRandom,
                      wildcard_dir: str,
                      _depth=0,
                      _resolved_vars=None) -> str:
    """
    Iterative resolver:
      - Runs passes until no further replacements occur (or max passes reached).
      - Keeps unresolved variable/wildcard tokens intact for later passes instead of deleting them.
      - Uses placeholders during a pass to avoid infinite loops on unresolved tokens.
      - After the normal iterative passes, runs a final sweep attempting to resolve
        any remaining variable/wildcard tokens once more; removes ones that cannot be resolved.
    """
    indent = "  " * _depth
    print(f"{indent}Resolving (depth {_depth}) start: {repr(text)}")

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

        # local function to perform a single pass that may create placeholders for unresolved tokens.
        def _single_pass(s_text: str) -> str:
            nonlocal changed, placeholders
            # work on copy
            working = s_text

            # main processing loop (very similar to previous algorithm)
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
                        _resolved_vars=_resolved_vars
                    )

                    # bracket variable chaining logic (as before)
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
                            # re-roll with attempts to avoid duplicates
                            max_attempts = 12
                            attempt = 0
                            value_to_store = None
                            prev_set = set(chain_assigned_values)
                            last_try = None
                            while attempt < max_attempts:
                                attempt += 1
                                candidate = process_bracket(
                                    content, seeded_rng, wildcard_dir, _resolved_vars=_resolved_vars
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
                    rng = seeded_rng.next_rng()
                    candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=None)
                    if candidates:
                        replacement = rng.choice(candidates)
                    else:
                        replacement = None  # unresolved

                elif wc_name is not None and var_tok:
                    # assignment or origin-scoped recall: __origin^var__ or __origin^*__
                    if "*" in var_tok:
                        rng = seeded_rng.next_rng()
                        candidates = _collect_candidates(_resolved_vars, var_tok, origin_filter=wc_name)
                        if candidates:
                            replacement = rng.choice(candidates)
                        else:
                            replacement = None
                    else:
                        bucket = _resolved_vars.get(var_tok, {})
                        if wc_name in bucket:
                            replacement = bucket[wc_name]
                        else:
                            rng_for_this = seeded_rng.next_rng()
                            generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir)
                            if not generated or generated.strip() == full_token:
                                replacement = None
                            else:
                                replacement = resolve_wildcards(
                                    generated, seeded_rng, wildcard_dir,
                                    _depth=_depth + 1, _resolved_vars=_resolved_vars
                                )
                                _ensure_var_bucket(_resolved_vars, var_tok)
                                _resolved_vars[var_tok][wc_name] = replacement

                else:
                    # plain wildcard: __name__
                    rng_for_this = seeded_rng.next_rng()
                    generated = process_file_wildcard(wc_name, rng_for_this, wildcard_dir)
                    if not generated or generated.strip() == full_token:
                        replacement = None
                    else:
                        replacement = resolve_wildcards(
                            generated, seeded_rng, wildcard_dir,
                            _depth=_depth + 1, _resolved_vars=_resolved_vars
                        )

                # apply logic: if replacement is None -> unresolved this pass
                if replacement is None:
                    # create placeholder for this unresolved token so we don't re-process it in this pass
                    ph = next_placeholder()
                    placeholders[ph] = full_token
                    working = working[:m_file.start()] + ph + working[m_file.end():]
                    print(f"{indent}  [pass] placeholdering unresolved token {full_token!r} -> {ph!r}")
                    # do NOT set changed = True (no real replacement happened)
                else:
                    # replacement found -> apply it
                    working = working[:m_file.start()] + replacement + working[m_file.end():]
                    changed = True
                    working = _space_adjacent_wildcards(working)
                    print(f"{indent}  [pass] replaced {full_token!r} -> {replacement!r}")

            return working

        # run single pass
        new_text = _single_pass(text)

        # restore placeholders to original tokens for next pass attempts
        if placeholders:
            for ph, orig in placeholders.items():
                new_text = new_text.replace(ph, orig)
            # reset placeholders mapping and counter for subsequent passes
            placeholders = {}
            placeholder_counter = 0

        print(f"{indent}After pass {pass_no}: {repr(new_text)} (changed={changed})")

        # if nothing changed during this pass, we are stable — stop
        if not changed:
            text = new_text
            break

        # else continue another pass on the updated text
        text = new_text
        # ensure spacing normalization for next pass
        text = _space_adjacent_wildcards(text)
        continue

    else:
        # max_passes exhausted
        print(f"{indent}⚠️ Max passes ({max_passes}) reached; returning current text.")

    # --- Final sweep: try once more to resolve leftover variables/wildcards, then remove leftovers ---
    text = _final_sweep_resolve(text, seeded_rng, wildcard_dir, _resolved_vars, _depth)

    print(f"{indent}Resolving (depth {_depth}) result: {repr(text)}")
    return text
