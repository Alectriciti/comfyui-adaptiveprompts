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
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "prompt"

    def process(self, prompt, seed):
        rng = SeededRandom(seed)
        return (resolve_wildcards(prompt, rng, self.input_dir),)


NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptRewrap": PromptRewrap,
    "PromptReplace": PromptReplace,
    "ShuffleTags": ShuffleTags,
    "ShuffleTagsAdvanced": ShuffleTagsAdvanced,
    "CleanupTags": CleanupTags,
    "NormalizeLoraTags": LoraTagNormalizer,
    "StringMerger4": StringMerger4,
    "StringMerger8": StringMerger8
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptGenerator": "Prompt Generator 🎨",
    "PromptRewrap": "Prompt Rewrap 📦",
    "PromptReplace": "Prompt Replace 🔁",
    "ShuffleTags": "Shuffle Tags ♻️",
    "ShuffleTagsAdvanced": "Shuffle Tags ♻️ (Advanced)",
    "CleanupTags": "Cleanup Tags 🧹",
    "NormalizeLoraTags": "Normalize Lora Tags 🟰",
    "StringMerger4": "String Merger (4)",
    "StringMerger8": "String Merger (8)"
}