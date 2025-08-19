import os
from .string_utils import *
from .generator import resolve_wildcards, SeededRandom
from .prompt_repack import PromptRepack
from .prompt_replace import PromptReplace

class PromptGenerator:
    def __init__(self):
        self.input_dir = os.path.join(os.path.dirname(__file__), "wildcards")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "hide_comments": ("BOOLEAN", {"default": True, "tooltip": "Comments can be created ## like this##\nIt's recommmended to instantiate variables within comments"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "prompt"

    def process(self, prompt, seed, hide_comments):
        rng = SeededRandom(seed)

        # Find comment blocks
        comment_blocks = re.findall(r"##(.*?)##", prompt, flags=re.DOTALL)
        pre_resolved_vars = {}

        for block in comment_blocks:
            # Resolve the comment block for wildcards and capture variable assignments
            _ = resolve_wildcards(block, rng, self.input_dir, _resolved_vars=pre_resolved_vars)
        if hide_comments:
            # Remove comment blocks
            prompt = re.sub(r"##.*?##", "", prompt)

        result = resolve_wildcards(prompt, rng, self.input_dir, _resolved_vars=pre_resolved_vars)


        # Clean up extra spaces left by comment removal
        result = " ".join(result.split())
        return (result,)

