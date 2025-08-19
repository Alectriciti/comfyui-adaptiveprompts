import re
import random
from .generator import SeededRandom

class WeightLifter:
    """
    🏋🏼 Weight Lifter - Randomizes and manipulates prompt tag weights.

    Features:
    - Random mode: assigns weights between min/max.
    - Falloff / Falloff Inverse modes: gradually emphasize/de-emphasize tags
      based on their position in the prompt.
    - Keyword selection: apply custom weighting logic to matched tags.
    - Preserves or overrides existing weights.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "min_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 10.0, "step": 0.01}),
                "max_weight": ("FLOAT", {"default": 1.2, "min": 0.0, "max": 10.0, "step": 0.01}),
                "delimiter": ("STRING", {"default": ","}),
                "mode": (["RANDOM", "FALLOFF", "FALLOFF_INV"],),
                "preserve_existing": ("BOOLEAN", {"default": True}),
                "limit": ("INT", {"default": 0, "min": 0, "max": 999}),
                "keyword_selection": ("STRING", {"multiline": False, "default": ""}),
                "keyword_mode": (["PASS", "MAXIMIZE", "DIMINISH_OTHERS"],),
                "keyword_variance": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 5.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "prompt"

    def process(
        self, prompt, seed, min_weight, max_weight, delimiter, mode,
        preserve_existing, limit, keyword_selection, keyword_mode, keyword_variance
    ):
        rng = SeededRandom(seed)
        tags = [t.strip() for t in prompt.split(delimiter) if t.strip()]

        # Preprocess keyword selection
        keyword_list = [k.strip() for k in keyword_selection.split(",") if k.strip()]
        def match_keyword(tag):
            clean_tag = tag.lower().replace("_", " ")
            return any(k.lower().replace("_", " ") in clean_tag for k in keyword_list)

        results = []
        n_tags = len(tags)
        applied = 0

        for i, tag in enumerate(tags):
            # Extract existing weight
            match = re.match(r"^(.*?)(?::([\d.]+))?\)?$", tag)
            base = match.group(1).strip("() ")
            current_weight = float(match.group(2)) if match.group(2) else None
            is_kw = match_keyword(base)

            if preserve_existing and current_weight is not None:
                results.append(tag)
                continue

            if limit > 0 and applied >= limit:
                results.append(tag)
                continue

            # Determine weight
            if mode == "RANDOM":
                w = rng.uniform(min_weight, max_weight)

            elif mode == "FALLOFF":
                t = i / max(1, n_tags - 1)
                w = min_weight + (max_weight - min_weight) * (1 - t)

            elif mode == "FALLOFF_INV":
                t = i / max(1, n_tags - 1)
                w = min_weight + (max_weight - min_weight) * t

            # Keyword logic
            if keyword_list:
                if keyword_mode == "PASS":
                    if not is_kw:
                        results.append(base)
                        continue
                elif keyword_mode == "MAXIMIZE" and is_kw:
                    w = max_weight + rng.uniform(-keyword_variance, keyword_variance)
                elif keyword_mode == "DIMINISH_OTHERS" and not is_kw:
                    w = min_weight - rng.uniform(0, keyword_variance)

            w = max(0.0, round(w, 2))  # Clamp + format weight
            results.append(f"({base}:{w})")
            applied += 1

        return (delimiter.join(results),)
