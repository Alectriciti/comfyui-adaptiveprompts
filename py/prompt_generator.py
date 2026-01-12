"""
Adaptive Prompts: prompt_generator
The front end nodes for Prompt Generator
Designed by Alectriciti

Changes:
- Split Prompt Generator into two version, one compact/simple, one advanced
- Removed "Hide Comments" from the simple version (Hide Comments is true by default)
- The Advanced version now has the option to Hide Comments, as well as specify a directory for custom wildcards.
"""

import os
from .generator import resolve_wildcards, SeededRandom
from .string_utils import re
from .wildcard_utils import _normalize_input_context, _ensure_bucket_dict, build_category_options

class PromptGenerator:
    """
    Advanced Prompt Generator that accepts and returns a variable context suitable
    for chaining nodes. The context format used by generator.py is a mapping:
      _resolved_vars: { var_name: { origin_key: value_str, ... }, ... }

    This node:
      - Accepts an optional 'context' input that may be:
          * dict-of-dicts (origin_key -> value)  <- preferred, passed through
          * dict-of-lists (list of values)       <- converted to dict-of-dicts
          * dict-of-single-values                 <- converted to dict-of-dicts
      - Normalizes input to dict-of-dicts before calling resolve_wildcards
      - Returns (prompt_string, context_dict) where context_dict is dict-of-dicts.
    """

    def __init__(self):
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.input_dir = os.path.join(base_dir, "wildcards")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            },
            "optional": {
                "context": ("DICT", {}),  # optional incoming context
            },
        }

    RETURN_TYPES = ("STRING", "DICT")
    RETURN_NAMES = ("prompt", "context")
    FUNCTION = "process"
    CATEGORY = "adaptiveprompts/generation"

    # ---------- main ----------
    def process(self, prompt, seed, context=None):
        rng = SeededRandom(seed)

        # Normalize incoming context into dict-of-dicts (origin->value)
        normalized_context = _normalize_input_context(context)

        comment_blocks = re.findall(r"##(.*?)##", prompt, flags=re.DOTALL)
        
        for block in comment_blocks:
            _ = resolve_wildcards(block, rng, self.input_dir, _resolved_vars=normalized_context)
        
        prompt = re.sub(r"##.*?##", "", prompt, flags=re.DOTALL)
        
        result = resolve_wildcards(prompt, rng, self.input_dir, _resolved_vars=normalized_context)

        #if cleanup:
        #result = " ".join(result.split())

        for k, v in list(normalized_context.items()):
            if not isinstance(v, dict):
                normalized_context[k] = _ensure_bucket_dict(v)

        return (result, normalized_context)



class PromptGeneratorAdvanced:
    """
    Advanced Prompt Generator that accepts and returns a variable context suitable
    for chaining nodes. The context format used by generator.py is a mapping:
      _resolved_vars: { var_name: { origin_key: value_str, ... }, ... }

    This node:
      - Accepts an optional 'context' input that may be:
          * dict-of-dicts (origin_key -> value)  <- preferred, passed through
          * dict-of-lists (list of values)       <- converted to dict-of-dicts
          * dict-of-single-values                 <- converted to dict-of-dicts
      - Normalizes input to dict-of-dicts before calling resolve_wildcards
      - Returns (prompt_string, context_dict) where context_dict is dict-of-dicts.
    """

    @classmethod
    def INPUT_TYPES(cls):
        # build shared label list / map for wildcards folders
        labels, mapping, tooltip = build_category_options()
        cls._CATEGORY_LABELS = labels
        cls._CATEGORY_MAP = mapping
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "hide_comments": ("BOOLEAN", {"default": True}),
                "category": (labels, {"default": labels[0] if labels else "Default", "tooltip": tooltip}),
            },
            "optional": {
                "context": ("DICT", {}),  # optional incoming context
            },
        }

    RETURN_TYPES = ("STRING", "DICT")
    RETURN_NAMES = ("prompt", "context")
    FUNCTION = "process"
    CATEGORY = "adaptiveprompts/generation"

    # ---------- main ----------
    def process(self, prompt, seed, hide_comments, category=None, context=None):
        rng = SeededRandom(seed)

        # Normalize incoming context into dict-of-dicts (origin->value)
        normalized_context = _normalize_input_context(context)

        # Map category label to its folder (string only, no os.path.join here!)
        category_label = category if category is not None else (
            getattr(self.__class__, "_CATEGORY_LABELS", ["Default"])[0]
        )
        folder_map = getattr(self.__class__, "_CATEGORY_MAP", {}) or {}
        folder_name = folder_map.get(category_label, "wildcards")

        # ----- handle comment blocks first -----
        comment_blocks = re.findall(r"##(.*?)##", prompt, flags=re.DOTALL)
        for block in comment_blocks:
            _ = resolve_wildcards(block, rng, folder_name, _resolved_vars=normalized_context)

        if hide_comments:
            prompt = re.sub(r"##.*?##", "", prompt)

        # ----- resolve main prompt -----
        result = resolve_wildcards(prompt, rng, folder_name, _resolved_vars=normalized_context)

        # Ensure context buckets are normalized
        for k, v in list(normalized_context.items()):
            if not isinstance(v, dict):
                normalized_context[k] = _ensure_bucket_dict(v)

        return (result, normalized_context)



class PromptContextMerge:
    """
    Combines up to three incoming contexts into a single context suitable for
    feeding back into PromptGeneratorAdvanced (or resolve_wildcards).
    Merge rules:
      - If the same variable exists in multiple inputs, their values are appended (not overwritten).
      - Incoming value shapes accepted: dict-of-dicts, list-of-values, single-value.
      - Origin keys from incoming dict-of-dicts are preserved where possible; if collisions happen,
        unique suffixes are created to avoid clobbering.
      - Output is a dict[var_name] -> dict[origin_key -> value] (the generator.py shape).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "context_a": ("DICT", {}),
                "context_b": ("DICT", {}),
                "context_c": ("DICT", {}),
            }
        }

    RETURN_TYPES = ("DICT",)
    FUNCTION = "combine"
    CATEGORY = "adaptiveprompts/context"

    @staticmethod
    def _iter_items_normalized(ctx):
        """
        Yield pairs (var_name, (origin_key, value)) for an arbitrary ctx entry.
        Accepts dict-of-dicts, dict-of-lists, dict-of-single-values.
        """
        if not ctx:
            return
        for var, bucket in ctx.items():
            if isinstance(bucket, dict):
                for orig, val in bucket.items():
                    yield var, (str(orig), str(val))
            elif isinstance(bucket, (list, tuple, set)):
                i = 0
                for val in bucket:
                    yield var, (f"__combined_{i}", str(val))
                    i += 1
            else:
                yield var, ("__combined_0", str(bucket))

    def combine(self, context_a=None, context_b=None, context_c=None):
        combined = {}
        # keep counters per variable to generate unique names when needed
        counters = {}

        for ctx in (context_a, context_b, context_c):
            if not ctx:
                continue
            # ctx may itself be a dict-of-dicts or other shapes; iterate normalized
            for var, (orig_key, val) in self._iter_items_normalized(ctx):
                if var not in combined:
                    combined[var] = {}
                    counters[var] = 0

                # If orig_key collides, try to preserve original key by suffixing a counter
                key_to_use = orig_key
                if key_to_use in combined[var]:
                    # find a non-colliding key
                    while True:
                        key_to_use = f"{orig_key}_c{counters[var]}"
                        counters[var] += 1
                        if key_to_use not in combined[var]:
                            break

                combined[var][key_to_use] = val

        return (combined,)
