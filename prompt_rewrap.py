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


class PromptRewrap:
    def __init__(self):
        self.wildcard_dir = os.path.join(os.path.dirname(__file__), "wildcards")
        self.rewrapper_dir = os.path.join(os.path.dirname(__file__), "rewrapper")
        self.preprocessor = WildcardPreprocessor(self.wildcard_dir)
        self.preprocessor.preprocess()
        self._last_blacklist_file = None
        self._word_blacklist = set()
        self._wildcard_blacklist_patterns = []

    @classmethod
    def INPUT_TYPES(cls):
        rewrapper_dir = os.path.join(os.path.dirname(__file__), "rewrapper")
        blacklist_files = [f for f in os.listdir(rewrapper_dir) if f.endswith(".txt")]
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["per_word", "per_phrase", "both", "both_and_detect_tags"], {"default": "per_word"}),
                "chance": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "blacklist_file": (blacklist_files, {"default": "blacklist.txt"}),
                "refresh_cache": ("BOOLEAN", {"default": False}),  # <-- cache refresh toggle
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

    def _wrap_token(self, token: str, seeded_rng: SeededRandom, chance: float,
                    word_blacklist, wildcard_blacklist_patterns, cache) -> str:
        rng = seeded_rng.next_rng()
        trailing_punct = ''
        while token and token[-1] in ",.!?":
            trailing_punct = token[-1] + trailing_punct
            token = token[:-1]
        token_lower = token.lower()
        if token_lower in word_blacklist:
            return token + trailing_punct
        if rng.random() > chance:
            return token + trailing_punct
        matching_wildcards = []
        for wildcard_name, values in cache.items():
            if self._is_wildcard_blacklisted(wildcard_name, wildcard_blacklist_patterns):
                continue
            for val in values:
                if val.strip().lower() == token_lower:
                    matching_wildcards.append(wildcard_name)
                    break
        if matching_wildcards:
            selected = rng.choice(matching_wildcards)
            return f"__{selected}__{trailing_punct}"
        return token + trailing_punct

    def _detect_and_embed_tags_in_phrase(self, phrase: str, cache, wildcard_blacklist_patterns):
        if "__" in phrase:
            return phrase
        underscored = re.sub(r"\s+", "_", phrase)
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
        matches.sort(key=lambda m: (-(m[1] - m[0]), m[0]))
        selected = []
        for m in matches:
            if any(not (m[1] <= s[0] or s[1] <= m[0]) for s in selected):
                continue
            selected.append(m)
        selected.sort(key=lambda m: m[0])
        out = []
        last = 0
        for s, e, value, _wname in selected:
            out.append(phrase[last:s])
            out.append(value)
            last = e
        out.append(phrase[last:])
        return "".join(out)

    # ------------------ Rewrap core ------------------

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
            phrase_tokens = [p.strip() for p in string.split(",")]
            for i in range(len(phrase_tokens)):
                phrase_tokens[i] = self._wrap_token(phrase_tokens[i], seeded_rng, chance,
                                                    self._word_blacklist, self._wildcard_blacklist_patterns, cache)
            for i in range(len(phrase_tokens)):
                phrase_tokens[i] = self._detect_and_embed_tags_in_phrase(
                    phrase_tokens[i], cache, self._wildcard_blacklist_patterns
                )
            intermediate = ", ".join(phrase_tokens)
            return (per_word_process(intermediate),)
        return (string,)
