import os
from .py.prompt_repack import PromptRepack
from .py.prompt_replace import PromptReplace
from .py.prompt_generator import PromptGenerator
from .py.weight_lifter import WeightLifter
from .py.image_nodes import SaveImageAndText
from .py.prompt_alias import PromptAliasSwap
from .py.prompt_trimmer import PromptTrimmer
from .py.prompt_shuffle import PromptShuffle, PromptShuffleAdvanced
from .py.string_utils import *
from .py.misc_utils import *
from .py.math_utils import *

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
    "TagCounter": TagCounter,
    "SaveImageAndText": SaveImageAndText,
    "RandomFloat": RandomFloat,
    "RandomFloats": RandomFloats4,
    "RandomInteger": RandomInteger,
    "RandomIntegers": RandomIntegers4,
    
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
    "TagCounter": "Tag Counter",
    "SaveImageAndText": "Save Image And Text",
    "RandomFloat": "Random Float",
    "RandomFloats": "Random Floats 4",
    "RandomInteger": "Random Integer",
    "RandomIntegers": "Random Integers 4",
}

def register_nodes(comfy):
    for name, cls in NODE_CLASS_MAPPINGS.items():
        display_name = NODE_DISPLAY_NAME_MAPPINGS.get(name, name)
        comfy.register_node(cls, display_name=display_name)
