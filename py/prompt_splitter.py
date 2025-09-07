import math
import random

LORA_PATTERN = r"<lora:[^>]+>"

class PromptSplitter:
    """
    A ComfyUI custom node that trims or keeps parts of a prompt string
    according to different probabilistic and deterministic strategies.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"multiline": True}),
                "quantity": ("INT", {
                    "default": 1,
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "tooltip": "The number of sections to either KEEP or REMOVE depending on QUANTITY_MODE."
                }),
                "quantity_mode": ([
                    "REMOVE",
                    "KEEP"
                ], {
                    "default": "REMOVE",
                    "tooltip": "Determines how 'quantity' is interpreted:\n\n"
                               "REMOVE: Remove 'quantity' sections based on the selected MODE.\n"
                               "KEEP: Ensure the final prompt has exactly 'quantity' sections (rest are trimmed)."
                }),
                "keep_first_sections": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "tooltip": "The number of sections at the beginning of the prompt to protect.\n"
                               "These will never be trimmed, even if selected mathematically."
                }),
                "mode": ([
                    "RANDOM",
                    "RANDOM_GRADUAL",
                    "RANDOM_EXPONENTIAL",
                    "RANDOM_SQRT",
                    "RANDOM_MIDDLE",
                    "TRIM_BEGINNING",
                    "TRIM_END",
                ], {
                    "default": "RANDOM",
                    "tooltip":
                        "RANDOM: Removes random sections.\n\n"
                        "RANDOM_GRADUAL: Probability of removal increases linearly as position moves forward.\n\n"
                        "RANDOM_EXPONENTIAL: Very low chance early, then ramps up exponentially towards the end.\n\n"
                        "RANDOM_SQRT: High chance early, flattens out later.\n\n"
                        "RANDOM_MIDDLE: Highest chance to trim near the middle of the prompt.\n\n"
                        "TRIM_BEGINNING: Absolutely removes from the start.\n\n"
                        "TRIM_END: Absolutely removes from the end."
                }),
                "delimiter": ("STRING", {
                    "default": ",",
                    "tooltip": "Character or string used to split the prompt into sections."
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0x7FFFFFFF,
                    "tooltip": "Random seed for reproducibility. Use 0 for a random seed each run."
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("Trimmed", "Scraps")
    FUNCTION = "process"
    CATEGORY = "adaptiveprompts/processing"

    def process(self, string, quantity, quantity_mode, keep_first_sections, mode, delimiter, seed):
        # Split prompt
        sections = [s.strip() for s in string.split(delimiter) if s.strip()]
        if not sections:
            return "", ""

        # Handle KEEP mode by converting into equivalent "remove count"
        if quantity_mode == "KEEP":
            quantity_to_remove = max(0, len(sections) - quantity)
        else:  # REMOVE mode
            quantity_to_remove = min(quantity, len(sections))

        # Protect first N sections from trimming
        protected = sections[:keep_first_sections]
        candidate_sections = sections[keep_first_sections:]

        if seed != 0:
            random.seed(seed)

        indices_to_remove = self._select_indices(
            candidate_sections, quantity_to_remove, mode
        )

        trimmed, scraps = [], []
        for i, section in enumerate(candidate_sections):
            if i in indices_to_remove:
                scraps.append(section)
            else:
                trimmed.append(section)

        # Prepend protected sections back
        trimmed = protected + trimmed

        trimmed_str = delimiter.join(trimmed)
        scraps_str = delimiter.join(scraps)
        return trimmed_str, scraps_str

    def _select_indices(self, sections, count, mode):
        """Select which indices to remove from candidate sections"""
        n = len(sections)
        if count <= 0 or n == 0:
            return set()

        indices = list(range(n))

        # Deterministic modes
        if mode == "TRIM_BEGINNING":
            return set(indices[:count])
        elif mode == "TRIM_END":
            return set(indices[-count:])

        # Probabilistic weighting
        weights = []
        for i in range(n):
            pos = (i + 1) / n
            if mode == "RANDOM":
                weights.append(1.0)
            elif mode == "RANDOM_GRADUAL":
                weights.append(pos)
            elif mode == "RANDOM_EXPONENTIAL":
                weights.append(pos ** 3)  # stronger ramp
            elif mode == "RANDOM_SQRT":
                weights.append(math.sqrt(pos))
            elif mode == "RANDOM_MIDDLE":
                mid = 0.5
                dist = abs(pos - mid)
                weights.append(1 - dist * 2)  # triangle peak at middle
            else:
                weights.append(1.0)

        # Normalize weights
        total = sum(weights)
        if total == 0:
            weights = [1] * n
            total = n
        norm_weights = [w / total for w in weights]

        # Pick without replacement
        chosen = set()
        while len(chosen) < count and indices:
            idx = random.choices(indices, weights=norm_weights, k=1)[0]
            chosen.add(idx)
            remove_idx = indices.index(idx)
            indices.pop(remove_idx)
            norm_weights.pop(remove_idx)
            if norm_weights:
                s = sum(norm_weights)
                norm_weights = [w / s for w in norm_weights]

        return chosen