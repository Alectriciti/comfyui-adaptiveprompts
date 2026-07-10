import os
from .py.prompt_repack import PromptRepack
from .py.prompt_replace import PromptReplace
from .py.prompt_generator import PromptGenerator, PromptGeneratorAdvanced, PromptSequencer, PromptContextMerge, PromptSetVariable
from .py.weight_lifter import WeightLifter
from .py.image_nodes import SaveImageAndText
from .py.prompt_alias import PromptAliasSwap
from .py.prompt_splitter import PromptSplitter
from .py.prompt_mixer import PromptMixer
from .py.prompt_shuffle import PromptShuffle, PromptShuffleAdvanced
from .py.lora_utils import *
from .py.string_utils import *
from .py.misc_utils import *
from .py.math_utils import *
from aiohttp import web
from server import PromptServer
from .py.config import get_all_config, set_config

@PromptServer.instance.routes.get("/adaptive_prompts/config")
async def get_config_route(request):
    return web.json_response(get_all_config())

@PromptServer.instance.routes.post("/adaptive_prompts/config")
async def set_config_route(request):
    try:
        data = await request.json()
        for key, value in data.items():
            set_config(key, value) 
        
        print(f"[Adaptive Prompts] Config Updated: {data}")
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "PromptGenerator": PromptGenerator,
    "PromptGeneratorAdvanced": PromptGeneratorAdvanced,
    "PromptSequencer": PromptSequencer,
    "PromptRepack": PromptRepack,
    "PromptAliasSwap": PromptAliasSwap,
    "PromptReplace": PromptReplace,
    "WeightLifter": WeightLifter,
    "PromptSplitter": PromptSplitter,
    "PromptMixer": PromptMixer,
    "PromptShuffle": PromptShuffle,
    "PromptShuffleAdvanced": PromptShuffleAdvanced,
    "PromptContextMerge": PromptContextMerge,
    "PromptCleanup": PromptCleanup,
    "NormalizeLoraTags": LoraTagNormalizer,
    "StringSplit": StringSplit,
    "StringAppend3": StringAppend3,
    "StringAppend8": StringAppend8,
    "ScaledSeedGenerator": ScaledSeedGenerator,
    "TagCounter": TagCounter,
    "SaveImageAndText": SaveImageAndText,
    "RandomFloats": RandomFloats4,
    "RandomIntegers": RandomIntegers4,
    "SetPromptVariable": PromptSetVariable,
    "LoadLoraTags": LoadLoraTags,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptGenerator": "💡 Prompt Generator 💡",
    "PromptGeneratorAdvanced": "💡 Prompt Generator 💡 (Advanced)",
    "PromptSequencer": "🎞️ Prompt Sequencer 🎞️",
    "PromptRepack": "📦 Prompt Repack 📦",
    "PromptAliasSwap": "📚 Prompt Alias Swap 📚",
    "PromptReplace": "🔁 Prompt Replace 🔁",
    "PromptContextMerge": "Prompt Context Merge",
    "WeightLifter": "🏋️‍♀️ Weight Lifter 🏋️‍♀️",
    "PromptSplitter": "✂️ Prompt Splitter ✂️",
    "PromptMixer": "🥣 Prompt Mixer 🥣",
    "PromptShuffle": "♻️ Prompt Shuffle ♻️",
    "PromptShuffleAdvanced": "♻️ Prompt Shuffle ♻️ (Advanced)",
    "PromptCleanup": "🧹 Prompt Cleanup 🧹",
    "NormalizeLoraTags": "🟰 Normalize Lora Tags 🟰",
    "StringSplit": "⛓️‍💥 String Split ⛓️‍💥",
    "StringAppend3": "🔗 String Append 🔗",
    "StringAppend8": "🔗 String Append 🔗",
    "ScaledSeedGenerator": "🌱 Scaled Seed Generator 🌱",
    "TagCounter": "Tag Counter",
    "SaveImageAndText": "Save Image And Text",
    "RandomFloats": "Random Floats 4",
    "RandomIntegers": "Random Integers 4",
    "SetPromptVariable": "🧮 Set Prompt Variable 🧮",
    "LoadLoraTags": "🏷️ Lora Tags Loader 🏷️",
}

def register_nodes(comfy):
    for name, cls in NODE_CLASS_MAPPINGS.items():
        display_name = NODE_DISPLAY_NAME_MAPPINGS.get(name, name)
        comfy.register_node(cls, display_name=display_name)
