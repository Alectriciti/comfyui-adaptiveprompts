import re
import os
from .generator import resolve_wildcards, SeededRandom

class PromptReplace:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"tooltip": "The original string", "multiline": True}),
                "target_string": ("STRING", {"tooltip": "The keywords to replace, separated by newlines.\nThis can be done with prompts via {1-2$$\n$$__wildcard__}", "multiline": True}),
                "replace_string": ("STRING", {"tooltip": "The string or wildcard to be replaced with. Each replacement action will re-roll the wildcard", "multiline": True}),
                "seed": ("INT", {"default": 0}),
                "limit": ("INT", {"default": 0}),  # 0 means unlimited
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "replace"
    CATEGORY = "adaptiveprompts/generation"

    def replace(self, string, target_string, replace_string, seed, limit):
        seeded_rng = SeededRandom(seed)


        wildcard_dir = os.path.join(os.path.dirname(__file__), "wildcards")
        # Expand target_string ONCE
        expanded_target = resolve_wildcards(target_string, seeded_rng, wildcard_dir)
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
                replacement = resolve_wildcards(replace_string, seeded_rng, wildcard_dir)
                replacements_done += 1
                return replacement

            result = regex.sub(repl_func, result)

        return (result,)