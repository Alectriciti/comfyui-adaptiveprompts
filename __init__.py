import os
from .string_utils import *
from .prompt_repack import PromptRepack
from .prompt_replace import PromptReplace
from .prompt_generator import PromptGenerator
from .weight_lifter import WeightLifter
from .image_nodes import SaveImageAndText
from .misc_utils import ScaledSeedGenerator
from .tag_alias import PromptAliasSwap

NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptRepack": PromptRepack,
    "PromptReplace": PromptReplace,
    "PromptTrimmer": PromptTrimmer,
    "WeightLifter": WeightLifter,
    "PromptShuffle": PromptShuffle,
    "PromptShuffleAdvanced": PromptShuffleAdvanced,
    "PromptCleanup": PromptCleanup,
    "PromptAliasSwap": PromptAliasSwap,
    "NormalizeLoraTags": LoraTagNormalizer,
    "StringSplit": StringSplit,
    "StringAppend3": StringAppend3,
    "StringAppend8": StringAppend8,
    "ScaledSeedGenerator": ScaledSeedGenerator,
    "SaveImageAndText": SaveImageAndText
    
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptGenerator": "Prompt Generator 💡",
    "PromptRepack": "Prompt Repack 📦",
    "PromptReplace": "Prompt Replace 🔁",
    "WeightLifter": "Weight Lifter 🏋️‍♀️",
    "PromptTrimmer": "Prompt Trimmer ✂️",
    "PromptShuffle": "Prompt Shuffle ♻️",
    "PromptShuffleAdvanced": "Prompt Shuffle ♻️ (Advanced)",
    "PromptCleanup": "Prompt Cleanup 🧹",
    "PromptAliasSwap": "Prompt Alias Swap 🏷️",
    "NormalizeLoraTags": "Normalize Lora Tags 🟰",
    "StringSplit": "StringSplit",
    "StringAppend3": "String Append (3)",
    "StringAppend8": "String Append (8)",
    "ScaledSeedGenerator": "Scaled Seed Generator 🌱",
    "SaveImageAndText": "Save Image And Text"
}

def register_nodes(comfy):
    for name, cls in NODE_CLASS_MAPPINGS.items():
        display_name = NODE_DISPLAY_NAME_MAPPINGS.get(name, name)
        comfy.register_node(cls, display_name=display_name)
