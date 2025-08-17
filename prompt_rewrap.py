import re
import os
import random
from .generator import SeededRandom


class WildcardPreprocessor:
    def __init__(self, wildcard_dir):
        self.wildcard_dir = wildcard_dir
        self.cache = {}  # Maps wildcard_name -> list of valid words

    def preprocess(self):
        """Load all wildcard files into memory, ignoring metadata and comments."""
        for root, _, files in os.walk(self.wildcard_dir):
            for filename in files:
                if not filename.endswith(".txt"):
                    continue

                # support subfolders in cache key: "environment/cave"
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
        self.preprocessor.preprocess()  # Preload all wildcards

    @classmethod
    def INPUT_TYPES(cls):
        rewrapper_dir = os.path.join(os.path.dirname(__file__), "rewrapper")
        blacklist_files = [f for f in os.listdir(rewrapper_dir) if f.endswith(".txt")]
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["per_word", "per_phrase", "both"], {"default": "per_word"}),
                "chance": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "blacklist_file": (blacklist_files, {"default": "blacklist.txt", "tooltip": "A list of words or wildcards to be ignored in this process\nFiles are located in /rewrapper/"})
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "hotswap"
    CATEGORY = "wildcards"

    def load_blacklist(self, filename):
        """Return a tuple (word_blacklist, wildcard_blacklist)."""
        path = os.path.join(self.rewrapper_dir, filename)
        words, wildcards = set(), set()
        if not os.path.exists(path):
            return words, wildcards

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("__") and line.endswith("__"):
                    wildcards.add(line.strip("_").lower())  # e.g. "__animal__" -> "animal"
                else:
                    words.add(line.lower())
        return words, wildcards

    def hotswap(self, string, mode, chance, seed, blacklist_file):
        cache = self.preprocessor.get_cache()
        seeded_rng = SeededRandom(seed)

        word_blacklist, wildcard_blacklist = self.load_blacklist(blacklist_file)

        def wrap_token(token: str) -> str:
            rng = seeded_rng.next_rng()

            # strip trailing punctuation
            trailing_punct = ''
            while token and token[-1] in ",.!?":
                trailing_punct = token[-1] + trailing_punct
                token = token[:-1]

            token_lower = token.lower()

            # Rule 1: skip if token is blacklisted as a word
            if token_lower in word_blacklist:
                return token + trailing_punct

            # chance roll per token
            if rng.random() > chance:
                return token + trailing_punct

            # Rule 2: search for wildcards, but skip those on the blacklist
            matching_wildcards = []
            for wildcard, values in cache.items():
                if wildcard in wildcard_blacklist:
                    continue
                for val in values:
                    if val.strip().lower() == token_lower:
                        matching_wildcards.append(wildcard)
                        break

            if matching_wildcards:
                selected = rng.choice(matching_wildcards)
                return f"__{selected}__{trailing_punct}"
            return token + trailing_punct

        if mode == "per_word":
            tokens = string.split()
            for i in range(len(tokens)):
                tokens[i] = wrap_token(tokens[i])
            return (" ".join(tokens),)

        elif mode == "per_phrase":
            tokens = [p.strip() for p in string.split(",")]
            for i in range(len(tokens)):
                tokens[i] = wrap_token(tokens[i])
            return (", ".join(tokens),)

        elif mode == "both":
            # Step 1: per_phrase
            phrase_tokens = [p.strip() for p in string.split(",")]
            for i in range(len(phrase_tokens)):
                phrase_tokens[i] = wrap_token(phrase_tokens[i])
            intermediate = ", ".join(phrase_tokens)

            # Step 2: per_word on the intermediate string
            word_tokens = intermediate.split()
            for i in range(len(word_tokens)):
                word_tokens[i] = wrap_token(word_tokens[i])
            return (" ".join(word_tokens),)

        return (string,)


