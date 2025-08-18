import os
from .string_utils import *
from .generator import resolve_wildcards, SeededRandom
from .prompt_rewrap import PromptRewrap
from .prompt_replace import PromptReplace
from .prompt_generator import PromptGenerator

# ---------------- Node Mappings ----------------

NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptRewrap": PromptRewrap,
    "PromptReplace": PromptReplace,
    "ShuffleTags": ShuffleTags,
    "ShuffleTagsAdvanced": ShuffleTagsAdvanced,
    "CleanupTags": CleanupTags,
    "NormalizeLoraTags": LoraTagNormalizer,
    "StringAppend4": StringAppend4,
    "StringAppend8": StringAppend8,
    "SaveImageAndText": SaveImageAndText
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
    "StringAppend8": "String Append (8)",
    "SaveImageAndText": "Save Image And Text"
}

# ---------------- All Exports ----------------

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

def register_nodes(comfy):
    """
    Registers all nodes with a comfy UI instance, applying display names.
    Example usage:
        import comfy
        from your_package import register_nodes
        register_nodes(comfy)
    """
    for name, cls in NODE_CLASS_MAPPINGS.items():
        display_name = NODE_DISPLAY_NAME_MAPPINGS.get(name, name)
        comfy.register_node(cls, display_name=display_name)
