import os
import re
from typing import Dict, List, Tuple, Optional
from .generator import SeededRandom


# ----------------------------- Wildcard preprocessor -----------------------------

class WildcardPreprocessor:
    """
    Loads wildcards from /wildcards and keeps a sanitized list of (wildcard_name, raw_line)
    WITHOUT expanding {brackets}. Expansion (if any) happens later during indexing
    depending on the `index_brackets` flag.

    Sanitize rules before indexing:
      - Trim anything after the first '#' on a line (and the '#').
      - Remove all '%...%' segments (weights).
      - Ignore lines that are empty after trimming or that start with '!' or '#'.
      - RED FLAGS (skip whole line):
          1) Any comma present.
          2) Any occurrence of "__" (placeholder-like content).
          3) Any bracket that contains "$$".
          4) Nested brackets (depth > 1).
    """

    def __init__(self, wildcard_dir: str):
        self.wildcard_dir = wildcard_dir
        # store sanitized lines only (no expansion here)
        self.raw_entries: List[Tuple[str, str]] = []

    # ----------- helpers for parsing ------------

    @staticmethod
    def _strip_inline_comments(line: str) -> str:
        """
        Remove everything from the first '#' to the end of line (no escaping).
        Also trims the result.
        """
        if not line:
            return line
        hash_idx = line.find('#')
        if hash_idx != -1:
            line = line[:hash_idx]
        return line.strip()

    @staticmethod
    def _strip_weights(line: str) -> str:
        """
        Remove all %...% segments (used for weights).
        E.g., 'Epic Ninja %50%' -> 'Epic Ninja'
        """
        # remove multiple occurrences if present
        return re.sub(r'%[^%]*%', '', line)

    @staticmethod
    def _has_commas(line: str) -> bool:
        return ',' in line

    @staticmethod
    def _has_double_underscores(line: str) -> bool:
        return '__' in line

    @staticmethod
    def _scan_braces_info(line: str) -> Tuple[bool, bool]:
        """
        Return (has_nested, has_dollar_dollar_inside_any_brace)
        A simple depth scan that inspects content of each top-level {...}.
        """
        depth = 0
        has_nested = False
        has_dollardollar = False
        start_idx = -1
        for i, ch in enumerate(line):
            if ch == '{':
                if depth == 0:
                    start_idx = i + 1
                else:
                    has_nested = True
                depth += 1
            elif ch == '}':
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_idx != -1:
                        content = line[start_idx:i]
                        if '$$' in content:
                            has_dollardollar = True
                        start_idx = -1
        # if depth != 0, unbalanced braces; treat as nested/problematic
        if depth != 0:
            has_nested = True
        return has_nested, has_dollardollar

    @staticmethod
    def _is_red_flag_line(line: str) -> bool:
        if not line:
            return True
        if WildcardPreprocessor._has_commas(line):
            return True
        if WildcardPreprocessor._has_double_underscores(line):
            return True
        has_nested, has_dollardollar = WildcardPreprocessor._scan_braces_info(line)
        if has_nested or has_dollardollar:
            return True
        return False

    def preprocess(self):
        """
        Build sanitized raw_entries list: (wildcard_name, raw_line) without brace expansion.
        wildcard_name is derived from the .txt relative path (without extension), using '/' as sep.
        """
        self.raw_entries.clear()

        if not os.path.isdir(self.wildcard_dir):
            return

        for root, _, files in os.walk(self.wildcard_dir):
            for filename in sorted(files):
                if not filename.endswith(".txt"):
                    continue
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, self.wildcard_dir)
                wildcard_name = os.path.splitext(rel_path)[0].replace("\\", "/")

                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        for raw in f:
                            s = raw.strip()
                            if not s or s.startswith('#') or s.startswith('!'):
                                continue
                            # trim comments, weights, and whitespace
                            s = self._strip_inline_comments(raw)
                            s = self._strip_weights(s).strip()
                            if not s:
                                continue
                            # red-flag screen
                            if self._is_red_flag_line(s):
                                continue
                            # keep the sanitized line (no expansion here)
                            self.raw_entries.append((wildcard_name, s))
                except OSError:
                    # Skip unreadable file
                    continue

    def get_raw_entries(self) -> List[Tuple[str, str]]:
        return list(self.raw_entries)


# ----------------------------- Prompt Repack (optimized redesign) -----------------------------

class PromptRepack:
    """
    detection_mode:
      - prioritize_words: only per-word replacement (no phrase collapsing).
      - prioritize_phrase: replace longest phrases (underscore-joined) first, then leftover words.

    matching_mode:
      - exact:       no case-folding, no space→underscore conversion.
      - ignore_case: lower-case, no space→underscore conversion.
      - flexible:    lower-case + spaces→underscores (phrase-ready). (No hyphen magic.)

    Conflict resolution:
      - If a value appears in multiple wildcard files, choose a random allowed group per occurrence
        using SeededRandom (deterministic for a given seed).
    """

    # ------------------- ComfyUI metadata -------------------

    @classmethod
    def INPUT_TYPES(cls):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        rewrapper_dir = os.path.join(base_dir, "repack_files")
        blacklist_files = [f for f in os.listdir(rewrapper_dir) if f.endswith(".txt")] if os.path.isdir(rewrapper_dir) else []
        if not blacklist_files:
            blacklist_files = ["blacklist.txt"]

        detection_tip = (
            "Detection priority:\n"
            "- prioritize_words: replace individual words only.\n"
            "- prioritize_phrase: replace longest underscore-joined phrases first, then words."
        )
        matching_tip = (
            "Matching rules:\n"
            "- exact: no case folding; no space→underscore.\n"
            "- ignore_case: lower-case input only.\n"
            "- flexible (default): lower-case + spaces→underscores."
        )

        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "detection_mode": (["prioritize_words", "prioritize_phrase"], {"default": "prioritize_phrase", "tooltip": detection_tip}),
                "matching_mode": (["exact", "ignore_case", "flexible"], {"default": "flexible", "tooltip": matching_tip}),
                "index_brackets": ("BOOLEAN", {"default": False, "tooltip": "If true, expand {a|b} combos into all indexed variants. Otherwise, lines with braces are skipped from indexing."}),
                "chance": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "blacklist_file": (blacklist_files, {"default": "blacklist.txt"}),
                "refresh_cache": ("BOOLEAN", {"default": False, "tooltip": "Reload wildcards and blacklist caches."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "repack"
    CATEGORY = "wildcards"

    # ------------------- init & paths -------------------

    def __init__(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.wildcard_dir = os.path.join(base_dir, "wildcards")
        self.rewrapper_dir = os.path.join(base_dir, "repack_files")
        self.preprocessor = WildcardPreprocessor(self.wildcard_dir)
        self.preprocessor.preprocess()

        self._last_blacklist_file: Optional[str] = None
        self._word_blacklist: set = set()
        self._wildcard_blacklist_patterns: List[str] = []

        # cache of indices keyed by (matching_mode, index_brackets)
        # value shape: { "word": {key -> [groups]}, "phrase": {key -> [groups]} }
        self._indices_cache: Dict[Tuple[str, bool], Dict[str, Dict[str, List[str]]]] = {}

    # ------------------- blacklist helpers -------------------

    def _parse_blacklist_line(self, line: str):
        s = line.strip()
        if not s or s.startswith("#"):
            return None
        if s.startswith("__"):
            body = s[2:]
            if body.endswith("__"):
                body = body[:-2]
            body = body.strip().lower()
            if body:
                return ("wildcard", body)
            return None
        else:
            return ("word", s.lower())

    def _is_wildcard_blacklisted(self, wildcard_name: str, patterns) -> bool:
        name = wildcard_name.lower()
        for pat in patterns:
            if not pat:
                continue
            if pat.endswith("*"):
                if name.startswith(pat[:-1]):
                    return True
            else:
                if name == pat:
                    return True
        return False

    def load_blacklist(self, filename):
        """Return a tuple (word_blacklist, wildcard_blacklist_patterns)."""
        path = os.path.join(self.rewrapper_dir, filename)
        words, wildcard_patterns = set(), []
        if not os.path.exists(path):
            return words, wildcard_patterns
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                parsed = self._parse_blacklist_line(raw)
                if not parsed:
                    continue
                kind, value = parsed
                if kind == "word":
                    words.add(value)
                else:
                    wildcard_patterns.append(value)
        return words, wildcard_patterns

    # ------------------- uniform indexing & brace expansion -------------------

    @staticmethod
    def _uniform_index_key(s: str) -> str:
        """
        Lowercase, trim, and replace any run of whitespace with a single underscore.
        Do NOT unescape backslashes; do NOT touch underscores/hyphens, etc.
        """
        t = s.strip().lower()
        t = re.sub(r'\s+', '_', t)
        return t

    @staticmethod
    def _has_brace(s: str) -> bool:
        return '{' in s or '}' in s

    @staticmethod
    def _expand_braces_non_nested(text: str) -> List[str]:
        """
        Expand top-level {a|b|...} blocks (no nested braces, guaranteed by pre-filter).
        Supports multiple brace blocks per line (cartesian expansion).
        """
        # Split into segments alternating between literal and brace-choices
        segments: List[List[str]] = [[]]
        i = 0
        L = len(text)
        while i < L:
            if text[i] == '{':
                j = text.find('}', i + 1)
                if j == -1:
                    # Unbalanced; treat as literal (should not happen due to pre-filter)
                    for seg in segments:
                        seg.append(text[i])
                    i += 1
                    continue
                inner = text[i + 1:j]
                choices = [c.strip() for c in inner.split('|') if c.strip() != '']
                # cartesian product update
                new_segments: List[List[str]] = []
                for seg in segments:
                    for choice in choices:
                        new_segments.append(seg + [choice])
                segments = new_segments
                i = j + 1
            else:
                # append literal char to all current segments
                ch = text[i]
                for seg in segments:
                    if seg and isinstance(seg[-1], str) and not seg[-1].startswith('{'):  # last is literal run
                        seg[-1] = seg[-1] + ch
                    else:
                        seg.append(ch)
                i += 1

        # join pieces of each segment
        out: List[str] = []
        for seg in segments:
            out.append("".join(seg))
        return out

    def _build_indices(self, matching_mode: str, index_brackets: bool):
        cache_key = (matching_mode, index_brackets)
        if cache_key in self._indices_cache:
            return

        word_index: Dict[str, List[str]] = {}
        phrase_index: Dict[str, List[str]] = {}

        entries = self.preprocessor.get_raw_entries()

        for wildcard_name, value in entries:
            # If this line contains any braces and user doesn't want bracket indexing, skip it
            if self._has_brace(value):
                if not index_brackets:
                    continue
                # expand non-nested braces into all combos
                expanded_values = self._expand_braces_non_nested(value)
            else:
                expanded_values = [value]

            for v in expanded_values:
                key = self._uniform_index_key(v)
                if not key:
                    continue
                # classify by underscore presence: phrases contain '_', words do not
                if '_' in key:
                    bucket = phrase_index.setdefault(key, [])
                else:
                    bucket = word_index.setdefault(key, [])
                if wildcard_name not in bucket:
                    bucket.append(wildcard_name)

        self._indices_cache[cache_key] = {"word": word_index, "phrase": phrase_index}

    # ------------------- text normalization for search -------------------

    @staticmethod
    def _normalize_for_search(text: str, mode: str) -> Tuple[str, List[int]]:
        """
        Produce a normalized text and index map -> original indices.
        - exact:        identity (no case-change, no space→underscore)
        - ignore_case:  lower()
        - flexible:     lower() + spaces→underscore (runs collapse to single '_')
        """
        out_chars: List[str] = []
        idx_map: List[int] = []

        if mode == "exact":
            for i, ch in enumerate(text):
                out_chars.append(ch)
                idx_map.append(i)
            return "".join(out_chars), idx_map

        if mode == "ignore_case":
            for i, ch in enumerate(text):
                out_chars.append(ch.lower())
                idx_map.append(i)
            return "".join(out_chars), idx_map

        # flexible: lower + spaces -> underscores (collapse runs)
        i = 0
        L = len(text)
        while i < L:
            ch = text[i]
            if ch.isspace():
                # collapse whitespace run to a single underscore
                start = i
                while i < L and text[i].isspace():
                    i += 1
                out_chars.append('_')
                idx_map.append(start)
                continue
            out_chars.append(ch.lower())
            idx_map.append(i)
            i += 1
        return "".join(out_chars), idx_map

    @staticmethod
    def _iter_boundary_matches(haystack: str, needle: str, alnum_set=r"[A-Za-z0-9_]"):
        """
        Find non-overlapping occurrences of needle in haystack with token boundaries:
        (?<![A-Za-z0-9_])needle(?![A-Za-z0-9_])
        """
        if not needle:
            return
        pat = re.compile(rf"(?<!{alnum_set}){re.escape(needle)}(?!{alnum_set})")
        for m in pat.finditer(haystack):
            yield m.start(), m.end()

    # ------------------- core matching passes -------------------

    def _replace_phrases_first(self, text: str, phrase_index: Dict[str, List[str]],
                               matching_mode: str, rng: SeededRandom,
                               chance: float) -> str:
        """
        Longest (underscore-joined) phrase replacement, then words.
        Avoids replacing inside existing __placeholders__.
        """
        if not phrase_index:
            return text

        norm_text, idx_map = self._normalize_for_search(text, matching_mode)
        # find existing placeholders to avoid overlapping replacements
        placeholder_spans = [(m.start(), m.end()) for m in re.finditer(r'__.*?__', text)]

        # Build candidates: (start_orig, end_orig, allowed_groups[List[str]])
        candidates: List[Tuple[int, int, List[str]]] = []

        # Sort keys by length descending to prefer longer phrases
        keys_by_len = sorted(phrase_index.keys(), key=len, reverse=True)

        for key in keys_by_len:
            start = 0
            while True:
                pos = norm_text.find(key, start)
                if pos == -1:
                    break
                start = pos + 1
                s_orig = idx_map[pos]
                e_orig = idx_map[pos + len(key) - 1] + 1

                # skip overlaps with existing placeholders
                overlapped = False
                for ps, pe in placeholder_spans:
                    if not (e_orig <= ps or pe <= s_orig):
                        overlapped = True
                        break
                if overlapped:
                    continue

                groups = phrase_index[key]
                allowed = [g for g in groups if not self._is_wildcard_blacklisted(g, self._wildcard_blacklist_patterns)]
                if allowed:
                    candidates.append((s_orig, e_orig, allowed))

        if not candidates:
            return text

        # Keep non-overlapping longest-first
        candidates.sort(key=lambda t: (-(t[1] - t[0]), t[0]))
        selected: List[Tuple[int, int, List[str]]] = []

        def overlaps(a, b):
            return not (a[1] <= b[0] or b[1] <= a[0])

        for span in candidates:
            if any(overlaps((span[0], span[1]), (s[0], s[1])) for s in selected):
                continue
            # chance roll per candidate span
            if rng.next_rng().random() > chance:
                continue
            selected.append(span)

        if not selected:
            return text

        selected.sort(key=lambda t: t[0])
        out, last = [], 0
        for s, e, allowed_groups in selected:
            out.append(text[last:s])
            chosen = rng.next_rng().choice(allowed_groups)
            out.append(f"__{chosen}__")
            last = e
        out.append(text[last:])
        return "".join(out)

    def _key_from_token(self, token: str, matching_mode: str) -> str:
        """
        Build comparison key from a single token (no surrounding whitespace).
        """
        if matching_mode == "exact":
            return token
        elif matching_mode == "ignore_case":
            return token.lower()
        else:  # flexible
            # tokens won't usually have spaces, but keep symmetry
            t = token.lower()
            t = re.sub(r'\s+', '_', t)
            return t

    def _replace_words(self, text: str, word_index: Dict[str, List[str]],
                       matching_mode: str, rng: SeededRandom,
                       chance: float) -> str:
        """
        Per-word pass preserving spacing/punctuation. Skips existing __placeholders__ tokens.
        """
        if not word_index:
            return text

        out = []
        last = 0
        for m in re.finditer(r'\S+', text):
            out.append(text[last:m.start()])
            token = m.group(0)

            # don't touch placeholders
            if token.startswith("__") and token.endswith("__"):
                out.append(token)
                last = m.end()
                continue

            # peel simple trailing punctuation
            core = token
            trailing = ""
            while core and core[-1] in ",.!?;:":
                trailing = core[-1] + trailing
                core = core[:-1]
            if not core:
                out.append(token)
                last = m.end()
                continue

            # word blacklist (plain lowercase)
            if core.lower() in self._word_blacklist:
                out.append(token)
                last = m.end()
                continue

            key = self._key_from_token(core, matching_mode)
            groups = word_index.get(key)
            if not groups:
                out.append(token)
                last = m.end()
                continue

            allowed = [g for g in groups if not self._is_wildcard_blacklisted(g, self._wildcard_blacklist_patterns)]
            if not allowed:
                out.append(token)
                last = m.end()
                continue

            if rng.next_rng().random() > chance:
                out.append(token)
                last = m.end()
                continue

            chosen = rng.next_rng().choice(allowed)
            out.append(f"__{chosen}__{trailing}")
            last = m.end()

        out.append(text[last:])
        return "".join(out)

    # ------------------- ComfyUI entry -------------------

    def repack(self, string: str, detection_mode: str, matching_mode: str,
               index_brackets: bool, chance: float, seed: int,
               blacklist_file: str, refresh_cache: bool = False):

        # Refresh wildcards and indices if asked
        if refresh_cache:
            self.preprocessor.preprocess()
            self._indices_cache.clear()
            self._last_blacklist_file = None

        # (Re)load blacklist if new file or after refresh
        if self._last_blacklist_file != blacklist_file:
            self._word_blacklist, self._wildcard_blacklist_patterns = self.load_blacklist(blacklist_file)
            self._last_blacklist_file = blacklist_file

        # Build indices for current settings
        self._build_indices(matching_mode, index_brackets)
        cache_key = (matching_mode, index_brackets)
        word_index = self._indices_cache[cache_key]["word"]
        phrase_index = self._indices_cache[cache_key]["phrase"]

        rng = SeededRandom(seed)

        if detection_mode == "prioritize_words":
            out = self._replace_words(string, word_index, matching_mode, rng, chance)
            return (out,)

        # phrases first, then words
        with_phrases = self._replace_phrases_first(string, phrase_index, matching_mode, rng, chance)
        out = self._replace_words(with_phrases, word_index, matching_mode, rng, chance)
        return (out,)
