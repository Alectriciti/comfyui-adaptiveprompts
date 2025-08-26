import os
from .py.prompt_repack import PromptRepack
from .py.prompt_replace import PromptReplace
from .py.prompt_generator import PromptGenerator
from .py.weight_lifter import WeightLifter
from .py.image_nodes import SaveImageAndText
from .py.misc_utils import ScaledSeedGenerator
from .py.tag_alias import PromptAliasSwap
from .py.string_utils import *

NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptRepack": PromptRepack,
    "PromptAliasSwap": PromptAliasSwap,
    "PromptReplace": PromptReplace,
    "PromptTrimmer": PromptTrimmer,
    "WeightLifter": WeightLifter,
    "PromptShuffle": PromptShuffle,
    "PromptShuffleAdvanced": PromptShuffleAdvanced,
    "PromptCleanup": PromptCleanup,
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
    "PromptAliasSwap": "Prompt Alias Swap 📚",
    "PromptReplace": "Prompt Replace 🔁",
    "WeightLifter": "Weight Lifter 🏋️‍♀️",
    "PromptTrimmer": "Prompt Trimmer ✂️",
    "PromptShuffle": "Prompt Shuffle ♻️",
    "PromptShuffleAdvanced": "Prompt Shuffle ♻️ (Advanced)",
    "PromptCleanup": "Prompt Cleanup 🧹",
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
