import random

from comfy.comfy_types import ComfyNodeABC, InputTypeDict

class ScaledSeedGenerator(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls) -> InputTypeDict:
        return {
            "required": {
                "seed": ("INT", {"default": 30000, "min": 0, "max": 2**31-1, "step": 1, "tooltip":"The Base seed - Every other seed is ultimately controlled by this one.\nE.G. A rate of 0.5 will change the seed every 2 increments."}),
                "rate_b": ("FLOAT", {"default": 0.5, "min": 0.001, "max": 1.0, "step": 0.025}),
                "rate_c": ("FLOAT", {"default": 0.25, "min": 0.001, "max": 1.0, "step": 0.025}),
                "rate_d": ("FLOAT", {"default": 0.125, "min": 0.001, "max": 1.0, "step": 0.025}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT")
    RETURN_NAMES = ("Output A", "Output B", "Output C", "Output D")
    FUNCTION = "generate"
    CATEGORY = "Alectriciti/Seed"

    def _scaled_random(self, base_seed: int, rate: float) -> int:
        """
        Produce a reproducible pseudo-random integer, derived from base_seed,
        but only changing at intervals controlled by rate.
        """
        # Scale the seed index according to the rate
        group_index = int(base_seed * rate)

        # Use that index to seed the RNG so it's deterministic
        rng = random.Random(group_index)

        # Produce a 32-bit integer
        return rng.randint(0, 2**31 - 1)

    def generate(self, seed: int, rate_b: float, rate_c: float, rate_d: float):
        # Original seed (priority, untouched)
        random_a = seed

        # Variants (reproducible randoms derived from scaled grouping)
        random_b = self._scaled_random(seed, rate_b)
        random_c = self._scaled_random(seed, rate_c)
        random_d = self._scaled_random(seed, rate_d)

        return (random_a, random_b, random_c, random_d)