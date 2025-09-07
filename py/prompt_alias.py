import os
import re
import random
from typing import Dict, List, Tuple, Optional


class PromptAliasSwap:
    """
    Prompt Alias Swap
    - Loads alias groups once (cached), optionally refreshed live.
    - Finds candidate tags (tokens) per rules and swaps them using the alias group.
    - Preserves all non-tag text (whitespace, punctuation, weights, brackets, etc).

    Candidate token rules:
      • Allowed core chars: letters, digits, '_', '-', '.', ';'
      • PLUS a special suffix: parentheses are allowed ONLY when they immediately follow an underscore,
        either as literal:   _(...), or escaped:   _\(...\)
      • Everything else (commas, colons, brackets) is NOT part of tags.
      • We skip pure numbers like "1.0" to avoid weight hits.

    Normalization for lookup (prompt → aliases):
      • lowercased
      • '\(' and '\)' → '(' and ')'
      • '-' treated like '_' (so dash/underscore are interchangeable for matching)
      • spaces are collapsed to '_' (rare in tags, but safe)
    """

    # ---------------- ComfyUI node metadata ----------------
    @classmethod
    def INPUT_TYPES(cls):
        mode_tip = (
            "- ALWAYS: Always swap to a different alias from the same group\n"
            "- RANDOM: Randomly choose from the group, meaning it may re-select itself and the tag remains unchanged\n"
        )
        chance_tip = (
            "The probability that a tag is swapped\n"
        )

        alias_dir = cls._tag_alias_root()
        alias_files = [f for f in os.listdir(alias_dir) if f.endswith(".txt")] if os.path.exists(alias_dir) else []
        if not alias_files:
            alias_files = ["tags.txt"]

        return {
            "required": {
                "string": ("STRING", {"multiline": True, "tooltip": "The input prompt to process"}),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0x7FFFFFFF
                }),
                "alias_file": (alias_files, {
                    "default": "tags.txt",
                    "tooltip": "Choose a .txt alias file from the 'tag_alias' folder.\n.csv format not currently supported"
                }),
                "mode": (["ALWAYS", "RANDOM"], {"default": "ALWAYS", "tooltip": mode_tip}),
                "chance": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": chance_tip
                }),
                "refresh_file": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "If True, re-read the alias file and refresh cache."
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("Aliased String",)
    FUNCTION = "apply"
    CATEGORY = "adaptiveprompts/generation"

    # ---------------- Cache & file handling ----------------
    _CACHE: Dict[str, dict] = {}

    @classmethod
    def _tag_alias_root(cls) -> str:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        return os.path.join(base_dir, "tag_alias_files")

    @classmethod
    def _resolve_alias_path(cls, name: str) -> Optional[str]:
        if not name:
            return None
        if os.path.isabs(name) and os.path.exists(name):
            return name
        candidate = os.path.join(cls._tag_alias_root(), name)
        if os.path.exists(candidate):
            return candidate
        return None

    @staticmethod
    def _normalize_token(tok: str) -> str:
        t = tok.strip().lower()
        t = t.replace(r'\(', '(').replace(r'\)', ')')
        t = t.replace('-', '_')
        t = re.sub(r'\s+', '_', t)
        return t

    @classmethod
    def precache_files(cls, alias_file: str, force: bool = False) -> Optional[dict]:
        path = cls._resolve_alias_path(alias_file)
        if not path:
            return None

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None

        if (not force) and path in cls._CACHE and cls._CACHE[path].get("mtime") == mtime:
            return cls._CACHE[path]

        groups: List[List[str]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    parts = [p for p in parts if p]
                    if parts:
                        groups.append(parts)
        except OSError:
            return None

        norm_map: Dict[str, Tuple[List[str], List[str]]] = {}
        for grp in groups:
            grp_norm = [cls._normalize_token(x) for x in grp]
            for n in grp_norm:
                norm_map[n] = (grp, grp_norm)

        bundle = {"mtime": mtime, "groups": groups, "norm_map": norm_map, "path": path}
        cls._CACHE[path] = bundle
        return bundle

    # ---------------- Tokenization & swapping ----------------
    _TOK_WITH_PAREN = r'[A-Za-zA-Z0-9_.;\-]+_\([^)]+\)'
    _TOK_WITH_PAREN_ESC = r'[A-Za-zA-Z0-9_.;\-]+_\\\([^)]+\\\)'
    _TOK_PLAIN = r'[A-Za-zA-Z0-9_.;\-]+'
    _TOKEN_RE = re.compile(rf'({_TOK_WITH_PAREN}|{_TOK_WITH_PAREN_ESC}|{_TOK_PLAIN})')
    _NUMERIC_RE = re.compile(r'^\d+(?:\.\d+)?$')

    def _pick_replacement(self, rng: random.Random, mode: str, group: List[str], group_norm: List[str], matched_norm: str) -> str:
        if mode == "ALWAYS":
            candidates = [s for s, n in zip(group, group_norm) if n != matched_norm]
            return rng.choice(candidates) if candidates else group[0]
        else:  # "RANDOM"
            return rng.choice(group)

    # ---------------- ComfyUI execution ----------------
    def apply(self, string: str, seed: int, alias_file: str, refresh_file: bool, mode: str, chance: float):
        cache = self.precache_files(alias_file, force=refresh_file)
        if not cache or not cache.get("norm_map"):
            return (string,)

        rng = random.Random(seed) if seed != 0 else random.Random()

        out_parts = []
        last = 0

        for m in self._TOKEN_RE.finditer(string):
            tok = m.group(0)
            if self._NUMERIC_RE.fullmatch(tok):
                continue

            norm = self._normalize_token(tok)
            grp_info = cache["norm_map"].get(norm)
            if not grp_info:
                continue

            # Roll chance only if alias exists
            if rng.random() > chance:
                continue

            group, group_norm = grp_info
            replacement = self._pick_replacement(rng, mode, group, group_norm, norm)

            out_parts.append(string[last:m.start()])
            out_parts.append(replacement)
            last = m.end()

        out_parts.append(string[last:])
        return ("".join(out_parts),)
