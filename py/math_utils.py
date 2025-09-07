from typing import Tuple, Union
import random
from comfy.comfy_types import ComfyNodeABC

Number = Union[int, float]  # Wildcard type for math nodes

# -------------------------
# Random 4 Outputs Nodes
# -------------------------

class RandomFloats4(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "min_value": ("FLOAT", {"default": 0.0}),
                "max_value": ("FLOAT", {"default": 1.0}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})
            }
        }

    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("value1", "value2", "value3", "value4")
    FUNCTION = "generate"
    CATEGORY = "Math"

    def generate(self, min_value: float, max_value: float, seed: int) -> Tuple[float, float, float, float]:
        rng = random.Random(seed)
        return tuple(rng.uniform(min_value, max_value) for _ in range(4))


class RandomIntegers4(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "min_value": ("INT", {"default": 0}),
                "max_value": ("INT", {"default": 10}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT")
    RETURN_NAMES = ("value1", "value2", "value3", "value4")
    FUNCTION = "generate"
    CATEGORY = "Math"

    def generate(self, min_value: int, max_value: int, seed: int) -> Tuple[int, int, int, int]:
        rng = random.Random(seed)
        return tuple(rng.randint(min_value, max_value) for _ in range(4))
