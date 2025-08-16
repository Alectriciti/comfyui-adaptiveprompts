import os
from .string_utils import *
from .generator import resolve_wildcards, SeededRandom
from .prompt_rewrap import PromptRewrap
from .prompt_replace import PromptReplace


class PromptGenerator:
    def __init__(self):
        self.input_dir = os.path.join(os.path.dirname(__file__), "wildcards")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "seed": ("INT", {"default": 0}),
                "hide_comments": ("BOOLEAN", {"default": True, "tooltip": "Comments can be created using the # token.\nExample: #comment here# will be removed after processing is done.\nVariables can be assigned this way"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "prompt"

    def process(self, prompt, seed, hide_comments):
        rng = SeededRandom(seed)
        # First resolve all wildcards / variables
        result = resolve_wildcards(prompt, rng, self.input_dir)

        # Then optionally strip comments
        if hide_comments:
            # Remove everything between #...# (non-greedy)
            result = re.sub(r"#.*?#", "", result)

        # Clean up extra spaces left by comment removal
        result = " ".join(result.split())
        return (result,)


NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptRewrap": PromptRewrap,
    "PromptReplace": PromptReplace,
    "ShuffleTags": ShuffleTags,
    "ShuffleTagsAdvanced": ShuffleTagsAdvanced,
    "CleanupTags": CleanupTags,
    "NormalizeLoraTags": LoraTagNormalizer,
    "StringAppend4": StringAppend4,
    "StringAppend8": StringAppend8
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptGenerator": "Prompt Generator 🎨",
    "PromptRewrap": "Prompt Rewrap 📦",
    "PromptReplace": "Prompt Replace 🔁",
    "ShuffleTags": "Shuffle Tags ♻️",
    "ShuffleTagsAdvanced": "Shuffle Tags ♻️ (Advanced)",
    "CleanupTags": "Cleanup Tags 🧹",
    "NormalizeLoraTags": "Normalize Lora Tags 🟰",
    "StringAppend4": "String Append (4)",
    "StringAppend8": "String Append (8)"
}