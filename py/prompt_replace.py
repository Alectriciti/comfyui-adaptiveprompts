import re
import os
from .generator import resolve_wildcards, SeededRandom
from .prompt_generator import *

class PromptReplace:

    def __init__(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.input_dir = os.path.join(base_dir, "wildcards")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"tooltip": "The original string", "multiline": True}),
                "target_string": ("STRING", {"tooltip": "The keywords to replace, separated by newlines.\nThis can be done with prompts via {1-2$$\n$$__wildcard__}", "multiline": True}),
                "replace_string": ("STRING", {"tooltip": "The string or wildcard to be replaced with. Each replacement action will re-roll the wildcard", "multiline": True}),
                "seed": ("INT", {"default": 0}),
                "limit": ("INT", {"default": 0}),  # 0 means unlimited
                "debug": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "context": ("DICT", {}),  # optional incoming context
            },
        }

    RETURN_TYPES = ("STRING", "DICT")
    RETURN_NAMES = ("prompt", "context")
    FUNCTION = "replace"
    CATEGORY = "adaptiveprompts/generation"

    def replace(self, string, target_string, replace_string, seed, limit, debug, context=None):
        seeded_rng = SeededRandom(seed)

        # Normalize incoming context into dict-of-dicts (origin->value)
        normalized_context = PromptGenerator._normalize_input_context(context)

        # Expand target_string ONCE
        expanded_target = resolve_wildcards(target_string, seeded_rng, self.input_dir, _resolved_vars=normalized_context)
        targets = expanded_target.split("\n")

        result = string
        replacements_done = 0

        for target in targets:
            target = target.strip()
            if not target:
                continue

            # Escape regex special chars except '*' and '?'
            pattern = re.escape(target).replace(r"\*", ".*").replace(r"\?", ".")
            regex = re.compile(pattern)

            def repl_func(match):
                nonlocal replacements_done
                if limit != 0 and replacements_done >= limit:
                    return match.group(0)  # No change

                # Expand replace_string PER replacement
                replacement = resolve_wildcards(replace_string, seeded_rng, self.input_dir, _resolved_vars=normalized_context)
                if debug:
                    print(f"  replace {replacements_done}: {repr(replacement)}")
                replacements_done += 1
                return replacement

            result = regex.sub(repl_func, result)


        for k, v in list(normalized_context.items()):
            if not isinstance(v, dict):
                normalized_context[k] = self._ensure_bucket_dict(v)

        return (result, normalized_context)