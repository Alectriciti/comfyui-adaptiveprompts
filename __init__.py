import os
from .string_utils import *
from .generator import resolve_wildcards, SeededRandom
from .prompt_repack import PromptRepack
from .prompt_replace import PromptReplace
from .prompt_generator import PromptGenerator
from .weight_lifter import WeightLifter

# ---------------- Node Mappings ----------------
NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptRepack": PromptRepack,
    "PromptReplace": PromptReplace,
    "WeightLifter": WeightLifter,
    "PromptShuffle": PromptShuffle,
    "PromptShuffleAdvanced": PromptShuffleAdvanced,
    "PromptCleanup": PromptCleanup,
    "NormalizeLoraTags": LoraTagNormalizer,
    "StringAppend4": StringAppend4,
    "StringAppend8": StringAppend8,
    "SaveImageAndText": SaveImageAndText
}

# ---------------- Display Name Mappings ----------------
NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptGenerator": "Prompt Generator 💡",
    "PromptRepack": "Prompt Repack 📦",
    "PromptReplace": "Prompt Replace 🔁",
    "WeightLifter": "Weight Lifter 🏋️‍♀️",
    "PromptShuffle": "Prompt Shuffle ♻️",
    "PromptShuffleAdvanced": "Prompt Shuffle ♻️ (Advanced)",
    "PromptCleanup": "Prompt Cleanup 🧹",
    "NormalizeLoraTags": "Normalize Lora Tags 🟰",
    "StringAppend4": "String Append (4)",
    "StringAppend8": "String Append (8)",
    "SaveImageAndText": "Save Image And Text"
}

# ---------------- Node Registration ----------------
def register_nodes(comfy):
    """
    Registers all nodes with a ComfyUI instance and applies display names.
    Usage:
        import comfy
        from your_package import register_nodes
        register_nodes(comfy)
    """
    for name, cls in NODE_CLASS_MAPPINGS.items():
        display_name = NODE_DISPLAY_NAME_MAPPINGS.get(name, name)
        comfy.register_node(cls, display_name=display_name)
