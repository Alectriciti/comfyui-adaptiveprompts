import re
import os
import random
import sys
from .wildcard_preprocessor import WildcardPreprocessor

BRACKET_PATTERN = re.compile(r"\{([^{}]+)\}")
# Allow slashes and '*' inside wildcard names
FILE_PATTERN = re.compile(r"__([a-zA-Z0-9_\-/*]+?)__")
# Also allow '*' here so adjacent tokens with '*' get spaced
ADJ_WC_PATTERN = re.compile(r"(__[a-zA-Z0-9_\-/*]+__)(__[a-zA-Z0-9_\-/*]+__)")

class SeededRandom:
    def __init__(self, base_seed: int):
        self.seed = base_seed

    def next_rng(self) -> random.Random:
        self.seed += 1
        return random.Random(self.seed)

def is_file_wildcard(choice: str) -> bool:
    return bool(FILE_PATTERN.fullmatch(choice.strip()))

def process_bracket(content: str, seeded_rng: SeededRandom, wildcard_dir: str) -> str:
    count = 1
    separator = ", "
    choices_str = content

    parts = content.split("$$")
    if len(parts) >= 2:
        count_part = parts[0]
        if "-" in count_part:
            low, high = map(int, count_part.split("-"))
            count = seeded_rng.next_rng().randint(low, high)
        else:
            count = int(count_part)

        if len(parts) == 2:
            choices_str = parts[1]
        elif len(parts) >= 3:
            separator = parts[1].encode('utf-8').decode('unicode_escape')
            choices_str = "$$".join(parts[2:])

    choices = [c.strip() for c in choices_str.split("|") if c.strip()]
    rng = seeded_rng.next_rng()

    file_wildcards = [c for c in choices if is_file_wildcard(c)]
    non_file_wildcards = [c for c in choices if not is_file_wildcard(c)]

    results = []
    used_non_file = set()

    while len(results) < count:
        if not non_file_wildcards:
            pick = rng.choice(file_wildcards)
        else:
            available_non_file = [c for c in non_file_wildcards if c not in used_non_file]
            if available_non_file:
                pick = rng.choice(file_wildcards + available_non_file)
                if not is_file_wildcard(pick):
                    used_non_file.add(pick)
            else:
                if file_wildcards:
                    pick = rng.choice(file_wildcards)
                else:
                    used_non_file.clear()
                    continue

        pick_resolved = resolve_wildcards(pick, seeded_rng, wildcard_dir)
        results.append(pick_resolved)

    if ("__" in separator) or ("{" in separator):
        joined = results[0]
        for item in results[1:]:
            sep_resolved = resolve_wildcards(separator, seeded_rng, wildcard_dir)
            joined += sep_resolved + item
        return joined
    else:
        return separator.join(results)

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

def _choose_file_from_dir(dir_path: str, rng: random.Random, prefix: str | None = None) -> str | None:
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

def process_file_wildcard(name: str, rng: random.Random, wildcard_dir: str) -> str:
    """
    Supports:
      - __fruit__                    -> wildcards/fruit.txt
      - __fruit*__                   -> any root file starting with 'fruit'
      - __*__                        -> any root file
      - __fruit/papaya__             -> wildcards/fruit/papaya.txt
      - __fruit/*__                  -> random .txt inside wildcards/fruit/
      - __fruit/tropical/coconut*__  -> any .txt in that folder starting with 'coconut'civita
    """
    # Normalize accidental leading/trailing slashes inside the token
    name = name.strip("/")

    # Subfolder path?
    if "/" in name:
        dir_part, last = name.rsplit("/", 1)
        dir_path = os.path.join(wildcard_dir, dir_part)

        # Back-compat: trailing slash -> treat as /* (random in dir)
        if last == "":
            chosen = _choose_file_from_dir(dir_path, rng, prefix=None)
            if not chosen:
                return ""
            return _read_weighted_line(chosen, rng)

        # Directory wildcard cases
        if last == "*":
            chosen = _choose_file_from_dir(dir_path, rng, prefix=None)
            if not chosen:
                return ""
            return _read_weighted_line(chosen, rng)

        if last.endswith("*"):
            prefix = last[:-1]
            chosen = _choose_file_from_dir(dir_path, rng, prefix=prefix)
            if not chosen:
                return ""
            return _read_weighted_line(chosen, rng)

        # Concrete file in subfolder
        filepath = os.path.join(dir_path, f"{last}.txt")
        if not os.path.exists(filepath):
            return ""
        return _read_weighted_line(filepath, rng)

    # Root-level cases (no '/')
    if name == "*":
        chosen = _choose_file_from_dir(wildcard_dir, rng, prefix=None)
        if not chosen:
            return ""
        return _read_weighted_line(chosen, rng)

    if name.endswith("*"):
        prefix = name[:-1]
        chosen = _choose_file_from_dir(wildcard_dir, rng, prefix=prefix)
        if not chosen:
            return ""
        return _read_weighted_line(chosen, rng)

    # Concrete root file
    filepath = os.path.join(wildcard_dir, f"{name}.txt")
    if not os.path.exists(filepath):
        return ""
    return _read_weighted_line(filepath, rng)

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

def _space_adjacent_wildcards(s: str) -> str:
    return ADJ_WC_PATTERN.sub(r"\1 \2", s)

def resolve_wildcards(text: str, seeded_rng: SeededRandom, wildcard_dir: str, _depth=0) -> str:
    if _depth > 80:
        return text

    text = _space_adjacent_wildcards(text)

    # 1) Brackets first
    while True:
        match = BRACKET_PATTERN.search(text)
        if not match:
            break
        replacement = process_bracket(match.group(1), seeded_rng, wildcard_dir)
        text = text[:match.start()] + replacement + text[match.end():]
        text = _space_adjacent_wildcards(text)

    # 2) File wildcards (with / and * support)
    while True:
        match = FILE_PATTERN.search(text)
        if not match:
            break

        full_token = match.group(0)
        wc_name = match.group(1)

        rng_for_this = seeded_rng.next_rng()
        replacement = process_file_wildcard(wc_name, rng_for_this, wildcard_dir)

        # Skip unresolved or identity to avoid stalls
        if not replacement or replacement.strip() == full_token:
            text = text[:match.start()] + "" + text[match.end():]
            text = _space_adjacent_wildcards(text)
            continue

        replacement = resolve_wildcards(replacement, seeded_rng, wildcard_dir, _depth=_depth+1)

        text = text[:match.start()] + replacement + text[match.end():]
        text = _space_adjacent_wildcards(text)

    return text