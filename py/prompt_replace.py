import re
import os
from .generator import resolve_wildcards, SeededRandom
from .wildcard_utils import _normalize_input_context, _ensure_bucket_dict, build_category_options
from .prompt_generator import *
from .wildcard_utils import *

class PromptReplace:

    def __init__(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.input_dir = os.path.join(base_dir, "wildcards")

    @classmethod
    def INPUT_TYPES(cls):
        # build shared label list / map for wildcards folders
        labels, mapping, tooltip = build_category_options()
        cls._CATEGORY_LABELS = labels
        cls._CATEGORY_MAP = mapping

        return {
            "required": {
                "string": ("STRING", {"tooltip": "The original string", "multiline": True}),
                "target_string": ("STRING", {"tooltip": "The keywords to replace, separated by newlines.\nThis can be done with prompts via {1-2$$\n$$__wildcard__}", "multiline": True}),
                "replace_string": ("STRING", {"tooltip": "The string or wildcard to be replaced with. Each replacement action will re-roll the wildcard", "multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "limit": ("INT", {"default": 0}),
                "category": (labels, {"default": labels[0] if labels else "Default", "tooltip": tooltip}),
            },
            "optional": {
                "context": ("DICT", {}),
            },
        }

    RETURN_TYPES = ("STRING", "DICT")
    RETURN_NAMES = ("prompt", "context")
    FUNCTION = "replace"
    CATEGORY = "adaptiveprompts/generation"

    def replace(self, string, target_string, replace_string, seed, limit, category=None, context=None):
        seeded_rng = SeededRandom(seed)

        # Normalize incoming context into dict-of-dicts (origin->value)
        normalized_context = _normalize_input_context(context)

        # Expand target_string ONCE
        expanded_target = resolve_wildcards(target_string, seeded_rng, category, _resolved_vars=normalized_context)
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
                replacement = resolve_wildcards(replace_string, seeded_rng, category, _resolved_vars=normalized_context)
                #if debug:
                #    print(f"  replace {replacements_done}: {repr(replacement)}")
                replacements_done += 1
                return replacement

            result = regex.sub(repl_func, result)


        for k, v in list(normalized_context.items()):
            if not isinstance(v, dict):
                normalized_context[k] = _ensure_bucket_dict(v)

        return (result, normalized_context)