# prompt_sequencer.py
"""
Prompt Sequencer node for ComfyUI

- Deterministically iterates through wildcard files and bracket choices.
- Unlike Prompt Generator, this does NOT recursively parse wildcard files.
- Supports some level of nested brackets in the main input.
- Modes: FROM_START, FROM_END, PARALLEL
"""

import re
import os
import itertools
from typing import List, Tuple
from .wildcard_utils import build_category_options, _default_package_root

# Regex to recognize __file__ and optional ^var (we ignore ^var in sequencing)
FILE_PATTERN = re.compile(r"__(?:([a-zA-Z0-9_\-/*]+?))?(?:\^([a-zA-Z0-9_\-\*]+))?__")

# Reused helper: split top-level pipes inside braces (preserve exact segments)
def _split_top_level_pipes(s: str) -> List[str]:
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

# Load weighted file lines (supports %w% weights, but sequencing uses order of items)
def _parse_weighted_options(lines_iterable):
    items, weights = [], []
    for raw in lines_iterable:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # remove inline comments after unescaped '#'
        cleaned = re.split(r'(?<!\\)#', line)[0].strip()
        if not cleaned:
            continue
        m = re.search(r'(?<!\\)%([0-9]*\.?[0-9]+)%', cleaned)
        if m:
            w = float(m.group(1))
            cleaned = (cleaned[:m.start()] + cleaned[m.end():]).strip()
        else:
            w = 1.0
        cleaned = cleaned.replace(r'\%', '%')
        if cleaned:
            items.append(cleaned)
            weights.append(w)
    return items, weights

def _load_weighted_file(filepath: str) -> Tuple[List[str], List[float]]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return _parse_weighted_options(f)
    except OSError:
        return [], []

# Helper: try primary path first, then fallback to package 'wildcards' folder
def _load_weighted_file_with_fallback(fname: str, wildcard_dir: str) -> Tuple[List[str], List[float]]:
    """
    fname: filename without extension
    wildcard_dir: primary directory to search (may be absolute path or folder name)
    """
    # primary candidate
    primary_fp = os.path.join(wildcard_dir, f"{fname}.txt")
    items, weights = _load_weighted_file(primary_fp)
    if items:
        return items, weights

    # fallback to package root / wildcards
    fallback_root = os.path.join(_default_package_root(), "wildcards")
    fallback_fp = os.path.join(fallback_root, f"{fname}.txt")
    items, weights = _load_weighted_file(fallback_fp)
    return items, weights

# Utility: find matching bracket span start..end (supports nesting)
def _find_matching_brace(s: str, start_idx: int) -> int:
    depth = 0
    for i in range(start_idx, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1

# Build a sequence list for a bracket content (recursive)
def _expand_bracket_content(content: str, wildcard_dir: str) -> List[str]:
    """
    Given the content inside { ... }, returns a sequence list (in order).
    For each top-level choice separated by '|':
      - If the choice (after stripping) is exactly a file wildcard like "__fruit__",
        the bracket's sequence includes every line from that file (in file order).
      - If the choice contains any file wildcards, they will be expanded by Cartesian
        product substitution (so "{__fruit__ and pie}" => expands fruit items + " and pie").
      - If the choice contains nested braces, those braces themselves are expanded
        recursively (the expansion result is inserted in place).
      - Otherwise the choice is treated as a literal single entry.
    The function preserves original whitespace inside choices.
    """
    choices = _split_top_level_pipes(content)
    out = []

    for ch in choices:
        # if the whole choice is another bracket, e.g. {{...}|x}
        ch_stripped = ch.strip()
        if ch_stripped.startswith("{") and ch_stripped.endswith("}") and _find_matching_brace(ch_stripped, 0) == len(ch_stripped) - 1:
            # nested bracket: expand recursively (strip outer braces)
            inner = ch_stripped[1:-1]
            out.extend(_expand_bracket_content(inner, wildcard_dir))
            continue

        # find all file wildcard tokens inside this choice
        file_matches = list(FILE_PATTERN.finditer(ch))
        if not file_matches:
            # literal choice — just append as-is
            out.append(ch)
            continue

        # For each file token, get the sequence of items from that file
        replacement_lists = []
        for m in file_matches:
            fname = (m.group(1) or "").strip()
            if not fname:
                # empty file token -> treat as empty list
                replacement_lists.append([""])
            else:
                items, _weights = _load_weighted_file_with_fallback(fname, wildcard_dir)
                # Use file items in file order. If empty file -> use the raw token as a literal fallback
                if not items:
                    replacement_lists.append([m.group(0)])  # keep raw token
                else:
                    replacement_lists.append(items)

        # Now construct strings by replacing each wildcard by elements from the replacement lists
        # We will iterate cartesian product of replacement_lists
        # To replace properly, we need to produce a template that can be substituted.
        # We'll substitute successive matches left-to-right.
        slots = []
        for product_tuple in itertools.product(*replacement_lists):
            s = ch
            # Replace each match occurrence with the corresponding item (left-to-right).
            # Use a simple approach: find first match each time and replace once.
            def _replace_first_file_token(s_in, replacement):
                return FILE_PATTERN.sub(lambda mm: replacement, s_in, count=1)
            tmp = s
            for repl in product_tuple:
                tmp = _replace_first_file_token(tmp, repl)
            slots.append(tmp)
        out.extend(slots)

    return out

# Parse the entire input into a list of parts:
# each part is either ("text", literal) or ("slot", list_of_items)
def _parse_input_to_parts(text: str, wildcard_dir: str):
    parts = []
    i = 0
    N = len(text)
    while i < N:
        # find next FILE_PATTERN or '{'
        fm = FILE_PATTERN.search(text, i)
        next_brace = text.find("{", i)
        next_match_pos = None
        next_is_file = False
        if fm:
            next_match_pos = fm.start()
            next_is_file = True
        if next_brace != -1 and (next_match_pos is None or next_brace < next_match_pos):
            # brace is next
            if next_brace > i:
                parts.append(("text", text[i:next_brace]))
            end_brace = _find_matching_brace(text, next_brace)
            if end_brace == -1:
                # unmatched brace - treat as literal
                parts.append(("text", text[next_brace:next_brace+1]))
                i = next_brace + 1
                continue
            inner = text[next_brace + 1:end_brace]
            # Expand bracket content into a sequence list
            seq_items = _expand_bracket_content(inner, wildcard_dir)
            parts.append(("slot", seq_items))
            i = end_brace + 1
            continue
        elif fm:
            # file token next
            if fm.start() > i:
                parts.append(("text", text[i:fm.start()]))
            fname = (fm.group(1) or "").strip()
            # load file items with fallback
            if fname:
                items, _weights = _load_weighted_file_with_fallback(fname, wildcard_dir)
                if not items:
                    # if file empty or missing, include raw token as single entry
                    parts.append(("slot", [fm.group(0)]))
                else:
                    parts.append(("slot", list(items)))
            else:
                # bare token with no name -> treat as literal token
                parts.append(("slot", [fm.group(0)]))
            i = fm.end()
            continue
        else:
            # no more special tokens; rest is literal
            parts.append(("text", text[i:]))
            break
    return parts

# Compute selection indices for each slot given an index and a mode
def _select_indices_for_slots(lengths: List[int], index: int, mode: str) -> List[int]:
    # treat zero-length as length 1 to avoid division/modulo by zero
    lens = [l if l > 0 else 1 for l in lengths]
    total = 1
    for l in lens:
        total *= l
    # wrap index into the range
    if total > 0:
        index = index % total
    else:
        index = 0

    n = len(lens)
    idxs = [0] * n

    if mode == "PARALLEL":
        for j in range(n):
            L = lens[j]
            idxs[j] = index % L
        return idxs

    if mode == "FROM_START":
        # leftmost cycles fastest => slot 0 is least significant
        temp = index
        for j in range(n):
            L = lens[j]
            if L > 0:
                idxs[j] = temp % L
                temp //= L
            else:
                idxs[j] = 0
        return idxs

    # FROM_END: rightmost cycles fastest => last slot is least significant
    temp = index
    for j in range(n - 1, -1, -1):
        L = lens[j]
        if L > 0:
            idxs[j] = temp % L
            temp //= L
        else:
            idxs[j] = 0
    return idxs

# -------------------- ComfyUI-style node class --------------------
class PromptSequencer:
    @classmethod
    def INPUT_TYPES(cls):
        # build shared label list / map for wildcards folders
        labels, mapping, tooltip = build_category_options()
        cls._CATEGORY_LABELS = labels
        cls._CATEGORY_MAP = mapping
        retn = {
            "required": {
                "wildcards": ("STRING", {"multiline": True, "default": ""}),
                "index": ("INT", {"default": 0}),
                "mode": (["FROM_START", "FROM_END", "PARALLEL"], {"default": "FROM_START"}),
                "category": (labels, {"default": labels[0] if labels else "Default", "tooltip": tooltip}),
            }
        }
        return retn

    RETURN_TYPES = ("STRING",)
    FUNCTION = "sequence"
    CATEGORY = "adaptiveprompts/generation"

    def sequence(self, wildcards: str, index: int, mode: str, category=None, ):
        """
        Generate the result for the given index and mode.
        """
        # Resolve category label -> folder path (prefer absolute path if mapping provided),
        # otherwise join package root + folder name. If that folder doesn't exist, fallback to package 'wildcards'.
        category_label = category if category is not None else (
            getattr(self.__class__, "_CATEGORY_LABELS", ["wildcards"])[0]
        )
        folder_map = getattr(self.__class__, "_CATEGORY_MAP", {}) or {}
        folder_entry = folder_map.get(category_label, "wildcards")

        if os.path.isabs(folder_entry) and os.path.isdir(folder_entry):
            wildcard_dir = folder_entry
        else:
            wildcard_dir = os.path.join(_default_package_root(), folder_entry)

        default_wildcards = os.path.join(_default_package_root(), "wildcards")
        if not os.path.isdir(wildcard_dir):
            wildcard_dir = default_wildcards

        # parse into parts (text + slots)
        parts = _parse_input_to_parts(wildcards, wildcard_dir)

        # Collect slot lengths and slot positions
        slot_lengths = []
        slot_positions = []  # indices of parts that are slots
        for pi, part in enumerate(parts):
            if part[0] == "slot":
                slot_positions.append(pi)
                slot_lengths.append(max(1, len(part[1])))

        # If there are no slots, just return the input unchanged
        if not slot_positions:
            return (wildcards,)

        # compute selected index per slot
        sel_idxs = _select_indices_for_slots(slot_lengths, index, mode)

        # build output by substituting selected items
        out_chunks = []
        slot_counter = 0
        for part in parts:
            if part[0] == "text":
                out_chunks.append(part[1])
            else:
                items = part[1]
                L = len(items)
                sel_i = sel_idxs[slot_counter] if L > 0 else 0
                # guard
                if L == 0:
                    chosen = ""
                else:
                    chosen = items[sel_i % L]
                out_chunks.append(chosen)
                slot_counter += 1

        result = "".join(out_chunks)
        return (result,)
