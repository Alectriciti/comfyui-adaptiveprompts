import re
import os
import random
from .generator import SeededRandom


class WildcardPreprocessor:
    def __init__(self, wildcard_dir):
        self.wildcard_dir = wildcard_dir
        self.cache = {}

    def preprocess(self):
        """Load all wildcard files into memory"""
        self.cache.clear()
        for root, _, files in os.walk(self.wildcard_dir):
            for filename in files:
                if not filename.endswith(".txt"):
                    continue
                rel_path = os.path.relpath(os.path.join(root, filename), self.wildcard_dir)
                wildcard_name = os.path.splitext(rel_path)[0].replace("\\", "/").lower()

                values = []
                filepath = os.path.join(root, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("!"):
                            continue
                        # Remove inline comments after unescaped #
                        line = re.split(r'(?<!\\)#', line)[0].strip()
                        if line:
                            values.append(line)

                self.cache[wildcard_name] = values

    def get_cache(self):
        return self.cache


class PromptRepack:
    def __init__(self):
        self.wildcard_dir = os.path.join(os.path.dirname(__file__), "wildcards")
        self.rewrapper_dir = os.path.join(os.path.dirname(__file__), "repack")
        self.preprocessor = WildcardPreprocessor(self.wildcard_dir)
        self.preprocessor.preprocess()
        self._last_blacklist_file = None
        self._word_blacklist = set()
        self._wildcard_blacklist_patterns = []

    @classmethod
    def INPUT_TYPES(cls):
        rewrapper_dir = os.path.join(os.path.dirname(__file__), "repack")
        blacklist_files = [f for f in os.listdir(rewrapper_dir) if f.endswith(".txt")]
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "mode": ([
                    "per_word",
                    "per_phrase",
                    "both",
                    "both_and_detect_tags",
                    "detect_all"  # <--- new mode
                ], {"default": "per_word"}),
                "chance": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "blacklist_file": (blacklist_files, {"default": "blacklist.txt"}),
                "refresh_cache": ("BOOLEAN", {"default": False}),  # refresh toggle (wildcards + blacklist)
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "hotswap"
    CATEGORY = "wildcards"

    # ------------------ Blacklist helpers ------------------

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
                prefix = pat[:-1]
                if name.startswith(prefix):
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

    # ------------------ Core helpers ------------------

    def _values_equivalent(self, token_lower: str, value_lower: str) -> bool:
        """
        Consider 'legend_of_zelda' == 'legend of zelda' and exact-equal.
        """
        if token_lower == value_lower:
            return True
        if token_lower.replace("_", " ") == value_lower.replace("_", " "):
            return True
        if token_lower.replace("_", " ") == value_lower:
            return True
        if token_lower == value_lower.replace(" ", "_"):
            return True
        return False

    def _wrap_token(self, token: str, seeded_rng: SeededRandom, chance: float,
                    word_blacklist, wildcard_blacklist_patterns, cache) -> str:
        rng = seeded_rng.next_rng()

        # strip trailing punctuation
        trailing_punct = ''
        while token and token[-1] in ",.!?":
            trailing_punct = token[-1] + trailing_punct
            token = token[:-1]

        token_lower = token.lower()

        # skip if token is blacklisted as a word
        if token_lower in word_blacklist:
            return token + trailing_punct

        # chance roll per token
        if rng.random() > chance:
            return token + trailing_punct

        # search for wildcards, skip blacklisted wildcard files/folders (pattern support)
        matching_wildcards = []
        for wildcard_name, values in cache.items():
            if self._is_wildcard_blacklisted(wildcard_name, wildcard_blacklist_patterns):
                continue
            for val in values:
                v_lower = val.strip().lower()
                if not v_lower:
                    continue
                if self._values_equivalent(token_lower, v_lower):
                    matching_wildcards.append(wildcard_name)
                    break

        if matching_wildcards:
            selected = rng.choice(matching_wildcards)
            return f"__{selected}__{trailing_punct}"
        return token + trailing_punct

    def _detect_and_embed_tags_in_phrase(self, phrase: str, cache, wildcard_blacklist_patterns):
        """
        Old, phrase-local detection (kept for both_and_detect_tags).
        """
        if "__" in phrase:
            return phrase

        # Build underscored version for containment search
        underscored = []
        i = 0
        while i < len(phrase):
            if phrase[i].isspace():
                start = i
                while i < len(phrase) and phrase[i].isspace():
                    i += 1
                underscored.append("_")
            else:
                underscored.append(phrase[i])
                i += 1
        underscored = "".join(underscored)
        u_lower = underscored.lower()

        matches = []
        for wildcard_name, values in cache.items():
            if self._is_wildcard_blacklisted(wildcard_name, wildcard_blacklist_patterns):
                continue
            for val in values:
                v = val.strip()
                if not v:
                    continue
                v_lower = v.lower()
                start = 0
                while True:
                    idx = u_lower.find(v_lower, start)
                    if idx == -1:
                        break
                    matches.append((idx, idx + len(v), v, wildcard_name))
                    start = idx + 1

        if not matches:
            return phrase

        matches.sort(key=lambda m: (-(m[1] - m[0]), m[0]))  # longer first
        selected = []
        def overlaps(a, b):
            return not (a[1] <= b[0] or b[1] <= a[0])
        for m in matches:
            if any(overlaps((m[0], m[1]), (s[0], s[1])) for s in selected):
                continue
            selected.append(m)

        selected.sort(key=lambda m: m[0])
        out = []
        last = 0
        for s, e, value, _wname in selected:
            out.append(phrase[last:s])
            out.append(value)  # insert canonical underscored value
            last = e
        out.append(phrase[last:])
        return "".join(out)

    # ---------- New: global detection over the entire string ----------

    def _build_underscored_with_map(self, text: str):
        """
        Convert runs of whitespace to a single underscore, and build a mapping
        from normalized index -> original index.
        """
        norm_chars = []
        idx_map = []
        i = 0
        L = len(text)
        while i < L:
            ch = text[i]
            if ch.isspace():
                start = i
                while i < L and text[i].isspace():
                    i += 1
                norm_chars.append("_")
                idx_map.append(start)
            else:
                norm_chars.append(ch)
                idx_map.append(i)
                i += 1
        return "".join(norm_chars), idx_map

    def _iter_boundary_matches(self, haystack: str, needle: str, alnum_set=r"[A-Za-z0-9_]"):
        """
        Find non-overlapping occurrences of needle in haystack with token boundaries:
        (?<![A-Za-z0-9_])needle(?![A-Za-z0-9_])
        """
        if not needle:
            return
        pat = re.compile(rf"(?<!{alnum_set}){re.escape(needle)}(?!{alnum_set})")
        for m in pat.finditer(haystack):
            yield m.start(), m.end()

    def _detect_and_embed_tags_global(self, text: str, cache, wildcard_blacklist_patterns) -> str:
        """
        Global phrase detection across the entire string.
        - Detects both underscore and space variants.
        - Prefers multi-word (longer) matches; avoids overlaps.
        - Replaces matched spans in the ORIGINAL text with the canonical underscored value.
        """
        if "__" in text:
            # Already wrapped somewhere; still proceed, but avoid double-wrapping by selection rules
            pass

        lower_text = text.lower()
        underscored, u_map = self._build_underscored_with_map(lower_text)

        matches = []  # (start_orig, end_orig, canonical_underscored, wildcard_name, token_count, length)

        for wildcard_name, values in cache.items():
            if self._is_wildcard_blacklisted(wildcard_name, wildcard_blacklist_patterns):
                continue

            for raw in values:
                v = raw.strip()
                if not v:
                    continue

                # Canonical forms
                v_space = v.replace("_", " ").strip().lower()
                v_under = re.sub(r"\s+", "_", v_space)  # ensure single underscores
                token_count = len([t for t in re.split(r"[ _]+", v_under) if t])

                # 1) search spaced form in original lowercased text (word boundaries)
                for s, e in self._iter_boundary_matches(lower_text, v_space, alnum_set=r"[A-Za-z0-9]"):
                    start_orig, end_orig = s, e
                    matches.append((start_orig, end_orig, v_under, wildcard_name, token_count, end_orig - start_orig))

                # 2) search underscored form in underscored-normalized text (underscore aware boundaries)
                for s, e in self._iter_boundary_matches(underscored, v_under, alnum_set=r"[A-Za-z0-9_]"):
                    # map back to original indices
                    start_orig = u_map[s]
                    end_orig = u_map[e - 1] + 1
                    matches.append((start_orig, end_orig, v_under, wildcard_name, token_count, end_orig - start_orig))

        if not matches:
            return text

        # Prefer multi-word, then longer span, then earlier
        matches.sort(key=lambda m: (-m[4], -m[5], m[0]))

        selected = []
        def overlaps(a, b):
            return not (a[1] <= b[0] or b[1] <= a[0])

        for m in matches:
            rng = False
            if any(overlaps((m[0], m[1]), (s[0], s[1])) for s in selected):
                continue
            selected.append(m)

        if not selected:
            return text

        selected.sort(key=lambda m: m[0])

        out = []
        last = 0
        for start_orig, end_orig, v_under, _wname, _tokc, _len in selected:
            out.append(text[last:start_orig])
            out.append(v_under)  # embed canonical underscored value for later per_word wrapping
            last = end_orig
        out.append(text[last:])
        return "".join(out)

    # ------------------ Repack Core ------------------

    def hotswap(self, string, mode, chance, seed, blacklist_file, refresh_cache=False):
        # refresh wildcards + blacklist cache if requested
        if refresh_cache:
            self.preprocessor.preprocess()
            self._last_blacklist_file = None  # force reload
            refresh_cache = False

        # reload blacklist if new file or forced
        if self._last_blacklist_file != blacklist_file:
            self._word_blacklist, self._wildcard_blacklist_patterns = self.load_blacklist(blacklist_file)
            self._last_blacklist_file = blacklist_file

        cache = self.preprocessor.get_cache()
        seeded_rng = SeededRandom(seed)

        def per_word_process(text: str) -> str:
            tokens = text.split()
            for i in range(len(tokens)):
                tokens[i] = self._wrap_token(tokens[i], seeded_rng, chance,
                                             self._word_blacklist, self._wildcard_blacklist_patterns, cache)
            return " ".join(tokens)

        def per_phrase_process(text: str) -> str:
            tokens = [p.strip() for p in text.split(",")]
            for i in range(len(tokens)):
                tokens[i] = self._wrap_token(tokens[i], seeded_rng, chance,
                                             self._word_blacklist, self._wildcard_blacklist_patterns, cache)
            return ", ".join(tokens)

        if mode == "per_word":
            return (per_word_process(string),)

        elif mode == "per_phrase":
            return (per_phrase_process(string),)

        elif mode == "both":
            intermediate = per_phrase_process(string)
            return (per_word_process(intermediate),)

        elif mode == "both_and_detect_tags":
            # Step 1: per_phrase
            phrase_tokens = [p.strip() for p in string.split(",")]
            for i in range(len(phrase_tokens)):
                phrase_tokens[i] = self._wrap_token(phrase_tokens[i], seeded_rng, chance,
                                                    self._word_blacklist, self._wildcard_blacklist_patterns, cache)
            # Step 2: detect tags inside each phrase
            for i in range(len(phrase_tokens)):
                phrase_tokens[i] = self._detect_and_embed_tags_in_phrase(
                    phrase_tokens[i], cache, self._wildcard_blacklist_patterns
                )
            intermediate = ", ".join(phrase_tokens)
            # Step 3: per_word to actually wrap the embedded tokens
            return (per_word_process(intermediate),)

        elif mode == "detect_all":
            # Step 1: (optional) per_phrase exact matches
            intermediate = per_phrase_process(string)
            # Step 2: global detection (underscores & spaces, longest-first)
            intermediate = self._detect_and_embed_tags_global(intermediate, cache, self._wildcard_blacklist_patterns)
            # Step 3: per_word to wrap embedded tokens
            return (per_word_process(intermediate),)

        return (string,)
