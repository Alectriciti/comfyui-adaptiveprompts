import random
import re
import random

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from comfy.cli_args import args
from comfy.comfy_types import ComfyNodeABC, InputTypeDict

LORA_PATTERN = r"<lora:[^>]+>"
import random
from typing import Tuple

import random
from typing import Tuple

LORA_PATTERN = re.compile(r"<lora:[^>]+>")

class PromptCleanup:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING",),
                "cleanup_commas": ("BOOLEAN", {"default": True, "tooltip": "cleans up extra commas if there is no tag present between them"}),
                "cleanup_whitespace": ("BOOLEAN", {"default": True, "tooltip": "cleans up leading/trailing whitespace, then excessive whitespace"}),
                "remove_lora_tags": ("BOOLEAN", {"default": False, "tooltip": "completely removes lora tags from the string"}),
                "cleanup_newlines": (["false", "space", "comma"], {"default": "false", "tooltip": "replaces newlines (\\n) with a space or comma"}),
                "fix_brackets": (["false", "(parenthesis)", "[brackets]", "([both])"], {"default": "([both])", "tooltip": "removes stray, unpaired brackets/parentheses"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "adaptiveprompts/processing"

    @staticmethod
    def _remove_unmatched(s: str, open_ch: str, close_ch: str) -> str:
        """Removes unmatched brackets of one type while preserving valid pairs."""
        stack = []
        remove_idx = set()

        for i, ch in enumerate(s):
            if ch == open_ch:
                stack.append(i)
            elif ch == close_ch:
                if stack:
                    stack.pop()  # matched → keep both
                else:
                    remove_idx.add(i)  # unmatched close → remove later

        # any opens still in stack are unmatched → remove them
        remove_idx.update(stack)

        # build cleaned string
        return "".join(ch for i, ch in enumerate(s) if i not in remove_idx)

    @staticmethod
    def process(string, cleanup_commas, cleanup_newlines, cleanup_whitespace, remove_lora_tags, fix_brackets):
        # Stage 1: Remove LoRA tags
        if remove_lora_tags:
            string = re.sub(LORA_PATTERN, "", string)

        # Stage 2: Replace newlines with space
        if cleanup_newlines == "space":
            string = string.replace("\n", " ")
        elif cleanup_newlines == "comma":
            string = string.replace("\n", ", ")

        # Stage 3: Remove empty comma sections
        if cleanup_commas:
            # Iteratively remove leading commas
            while re.match(r"^[ \t]*,[ \t]*", string):
                string = re.sub(r"^[ \t]*,[ \t]*", "", string)

            # Iteratively remove trailing commas
            while re.search(r"[ \t]*,[ \t]*$", string):
                string = re.sub(r"[ \t]*,[ \t]*$", "", string)

            # Remove empty comma sections inside the string
            while re.search(r",[ \t]*,", string):
                string = re.sub(r",[ \t]*,", ",", string)

        # Stage 4: Fix stray brackets
        if fix_brackets != "false":
            if fix_brackets in ("(parenthesis)", "([both])"):
                string = PromptCleanup._remove_unmatched(string, "(", ")")
            if fix_brackets in ("[brackets]", "([both])"):
                string = PromptCleanup._remove_unmatched(string, "[", "]")

        # Stage 5: Whitespace cleanup
        if cleanup_whitespace:
            string = string.strip(" \t")
            string = re.sub(r"[ \t]{2,}", " ", string)              # collapse spaces/tabs
            string = re.sub(r"[ \t]*,[ \t]*", ", ", string)         # normalize comma spacing

        return (string,)




class StringAppend3:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string_1": ("STRING", {"default": "", "multiline": True}),
                "string_2": ("STRING", {"default": "", "multiline": True}),
                "string_3": ("STRING", {"default": "", "multiline": True}),
                "combine_mode": (["None", "Space", "Underscore", "Comma", "Newline"], {"default": "Comma"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "merge_strings"
    CATEGORY = "adaptiveprompts/utils"

    @staticmethod
    def merge_strings(string_1, string_2, string_3, combine_mode):
        # Extract all strings in order
        strings = [string_1, string_2, string_3]
        # Filter out empty strings
        strings = [s for s in strings if s.strip() != ""]
        # Join with newline
        if combine_mode =="Comma":
            connector = ", "
        elif combine_mode == "Space":
            connector = " "
        elif combine_mode == "Underscore":
            connector = "_"
        elif combine_mode =="Newline":
            connector = "\n"
        else:
            connector = ""
        merged = connector.join(strings)
        return (merged,)


class StringAppend8:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string_1": ("STRING", {"default": ""}),
                "string_2": ("STRING", {"default": ""}),
                "string_3": ("STRING", {"default": ""}),
                "string_4": ("STRING", {"default": ""}),
                "string_5": ("STRING", {"default": ""}),
                "string_6": ("STRING", {"default": ""}),
                "string_7": ("STRING", {"default": ""}),
                "string_8": ("STRING", {"default": ""}),
                "combine_mode": (["None", "Space", "Underscore", "Comma", "Newline"], {"default": "Comma"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "merge_strings"
    CATEGORY = "adaptiveprompts/utils"

    @staticmethod
    def merge_strings(string_1, string_2, string_3, string_4, string_5, string_6, string_7, string_8, combine_mode):
        # Extract all strings in order
        strings = [string_1, string_2, string_3, string_4, string_5, string_6, string_7, string_8]
        # Filter out empty strings
        strings = [s for s in strings if s.strip() != ""]
        # Join with newline
        if combine_mode =="Comma":
            connector = ", "
        elif combine_mode == "Space":
            connector = " "
        elif combine_mode == "Underscore":
            connector = "_"
        elif combine_mode =="Newline":
            connector = "\n"
        else:
            connector = ""
        merged = connector.join(strings)
        return (merged,)
    
class StringSplit(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls) -> InputTypeDict:
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "The input string to split."
                }),
                "start": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 99999,
                    "step": 1,
                    "tooltip": "Index of the first delimiter occurrence to split from."
                }),
                "end": ("INT", {
                    "default": 1,
                    "min": 0,
                    "max": 99999,
                    "step": 1,
                    "tooltip": "Index of the second delimiter occurrence to split until."
                }),
                "delimiter": ("STRING", {
                    "default": ",",
                    "tooltip": "The delimiter used to separate sections of the string."
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("String A", "String B", "String C")
    FUNCTION = "split_string"
    CATEGORY = "adaptiveprompts/utils"

    def split_string(self, text: str, start: int, end: int, delimiter: str):
        # Safety: empty delimiter is useless, default to ","
        if not delimiter:
            delimiter = ","

        parts = text.split(delimiter)

        # Clamp indices to valid ranges
        start = max(0, min(start, len(parts)))
        end = max(0, min(end, len(parts)))

        if start > end:
            start, end = end, start  # normalize swapped ranges

        # Slice into 3 buckets
        before = delimiter.join(parts[:start])
        middle = delimiter.join(parts[start:end])
        after = delimiter.join(parts[end:])

        return (before, middle, after)

class LoraTagNormalizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "total_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "tooltip": "The final weight of all the tags combined"}),
                "bounds": (["POSITIVE", "NEGATIVE", "BOTH"], {"default": "BOTH", "tooltip": "Only includes positive, negative, or both values.\nUsed to have separate control over positive and negative loras."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "normalize"
    CATEGORY = "adaptiveprompts/utils"

    def normalize(self, string: str, total_weight: float, bounds: str):
        """
        Normalize <lora:name:weight> tags.

        - Parses float weights; leaves tags with non-float weights untouched.
        - Ignores zero weights entirely.
        - BOUNDS controls which tags participate:
          POSITIVE: only >0
          NEGATIVE: only <0
          BOTH: all (magnitudes normalized, sign preserved)
        - Multiplies normalized proportions by total_weight.
        - Rounds output to 3 decimal places.
        """
        pattern = re.compile(r"<lora:([^:>]+):([^>]+)>")
        matches = list(pattern.finditer(string))

        # Collect parseable, non-zero lora entries
        entries = []
        for m in matches:
            full = m.group(0)
            name = m.group(1)
            raw_weight = m.group(2).strip()
            try:
                w = float(raw_weight)
            except Exception:
                # leave unparseable tags unchanged
                continue
            if w == 0.0:
                # explicitly ignore zero-weight tags
                continue
            entries.append({"full": full, "name": name, "weight": w})

        # nothing to normalize
        if not entries:
            return (string,)

        # Build normalized mapping keyed by the original full tag string
        normalized_map = {}

        if bounds == "POSITIVE":
            positives = [e for e in entries if e["weight"] > 0]
            total_pos = sum(e["weight"] for e in positives)
            if total_pos == 0:
                return (string,)
            for e in positives:
                new_val = (e["weight"] / total_pos) * total_weight
                normalized_map[e["full"]] = f"<lora:{e['name']}:{new_val:.3f}>"

        elif bounds == "NEGATIVE":
            negatives = [e for e in entries if e["weight"] < 0]
            total_neg_abs = sum(abs(e["weight"]) for e in negatives)
            if total_neg_abs == 0:
                return (string,)
            for e in negatives:
                # preserve negative sign while distributing by magnitude
                new_val = (e["weight"] / total_neg_abs) * total_weight
                normalized_map[e["full"]] = f"<lora:{e['name']}:{new_val:.3f}>"

        else:  # BOTH
            total_abs = sum(abs(e["weight"]) for e in entries)
            if total_abs == 0:
                return (string,)
            for e in entries:
                mag = (abs(e["weight"]) / total_abs) * total_weight
                sign = 1.0 if e["weight"] > 0 else -1.0
                new_val = mag * sign
                normalized_map[e["full"]] = f"<lora:{e['name']}:{new_val:.3f}>"

        # Replace tags using the original matched text as the key.
        def repl(m):
            orig = m.group(0)
            return normalized_map.get(orig, orig)

        new_string = pattern.sub(repl, string)
        return (new_string,)

