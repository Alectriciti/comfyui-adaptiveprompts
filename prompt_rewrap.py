import re
import os
import random
from .wildcard_preprocessor import WildcardPreprocessor
from .generator import SeededRandom

class PromptRewrap:
    def __init__(self):
        self.wildcard_dir = os.path.join(os.path.dirname(__file__), "wildcards")
        self.preprocessor = WildcardPreprocessor(self.wildcard_dir)
        self.preprocessor.preprocess()  # Preload all wildcards

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "mode": (["per_word", "per_phrase"], {"default": "per_word"}),
                "chance": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "hotswap"
    CATEGORY = "wildcards"

    def hotswap(self, string, mode, chance, seed):
        cache = self.preprocessor.get_cache()
        seeded_rng = SeededRandom(seed)

        def wrap_token(token: str) -> str:
            rng = seeded_rng.next_rng()

            # chance roll per token
            if rng.random() > chance:
                return token

            # strip only trailing comma/period for lookup; preserve for output
            trailing_punct = ''
            while token and token[-1] in ",.":
                trailing_punct = token[-1] + trailing_punct
                token = token[:-1]

            token_lower = token.lower()
            matching_wildcards = []

            for wildcard, values in cache.items():
                if mode == "per_word":
                    # exact equality only (single token match)
                    for val in values:
                        if val.strip().lower() == token_lower:
                            matching_wildcards.append(wildcard)
                            break
                else:  # per_phrase
                    # exact phrase equality against values
                    for val in values:
                        if val.strip().lower() == token_lower:
                            matching_wildcards.append(wildcard)
                            break

            if matching_wildcards:
                selected = rng.choice(matching_wildcards)
                return f"__{selected}__{trailing_punct}"
            return token + trailing_punct

        if mode == "per_word":
            tokens = string.split()
            for i in range(len(tokens)):
                tokens[i] = wrap_token(tokens[i])
            return (" ".join(tokens),)

        elif mode == "per_phrase":
            tokens = [p.strip() for p in string.split(",")]
            for i in range(len(tokens)):
                tokens[i] = wrap_token(tokens[i])
            return (", ".join(tokens),)

        return (string,)