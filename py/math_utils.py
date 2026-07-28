import random
import sys
from typing import Tuple, Union

from comfy.comfy_types import ComfyNodeABC

Number = Union[int, float]  # Wildcard type for math nodes

_INT_MIN = -0xFFFFFFFFFFFFFFFF
_INT_MAX = 0xFFFFFFFFFFFFFFFF
_FLOAT_MIN = -sys.float_info.max
_FLOAT_MAX = sys.float_info.max

# -------------------------
# Random 4 Outputs Nodes
# -------------------------

class RandomFloats4(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "min_value": ("FLOAT", {"default": 0.0, "min": _FLOAT_MIN, "max": _FLOAT_MAX, "step": 0.01}),
                "max_value": ("FLOAT", {"default": 1.0, "min": _FLOAT_MIN, "max": _FLOAT_MAX, "step": 0.01}),
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
                "min_value": ("INT", {"default": 0, "min": _INT_MIN, "max": _INT_MAX}),
                "max_value": ("INT", {"default": 10, "min": _INT_MIN, "max": _INT_MAX}),
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
