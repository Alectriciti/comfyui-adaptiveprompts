import random
import re
from typing import List, Tuple


LORA_PATTERN = r"<lora:[^>]+>"

class ShuffleTags:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"default": ""}),
                "separator": ("STRING", {"default": ","}),
                "limit": ("INT", {"default": 3, "min": 1, "max": 100}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})
            }
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("shuffled_string",)
    FUNCTION = "shuffle_strings"
    CATEGORY = "Custom Nodes"

    def shuffle_strings(self, string: str, separator: str, limit: int, seed: int) -> Tuple[str]:
    
        if seed is not None:
            random.seed(seed)
        
        parts = string.split(separator)
        random.shuffle(parts)
        selected_parts = parts[:limit]  # Take only 'limit' number of shuffled parts
        shuffled_string = separator.join(selected_parts)
        
        return (shuffled_string,)  # Return as a single string


def _clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _compute_strength(progress: float,
                      algorithm: str,
                      rng: random.Random,
                      decay_state: dict) -> float:
    """
    Returns a strength in [0, 1] for the current item, based on:
      - progress in [0,1] across the line
      - algorithm (RANDOM, LINEAR IN, LINEAR OUT, SHUFFLE_DECAY[_REVERSE])
      - cumulative decay (for SHUFFLE_DECAY variants)
    Mnemonic:
      - RANDOM:    strength ← rng.random()  (stdlib random)
      - LINEAR_IN: rises with position (in → stronger)
      - LINEAR_OUT:falls with position (out → weaker)
      - SHUFFLE_DECAY(_REVERSE): like LINEAR_IN but reduced by global budget
    """
    algo = algorithm.upper()

    if algo == "RANDOM":
        base = rng.random()
    elif algo == "LINEAR_IN":
        base = progress
    elif algo == "LINEAR_OUT":
        base = 1.0 - progress
    elif algo in ("SHUFFLE_DECAY", "SHUFFLE_DECAY_REVERSE"):
        base = progress
        budget = decay_state.get("budget", 1.0)
        base *= _clamp(budget, 0.0, 1.0)
    else:
        base = progress

    return max(0.0, min(1.0, base))

def _apply_decay(actual_delta_steps: int, max_amount: int, n: int, decay_state: dict):
    """
    Reduce global budget proportional to actual movement.
    Origin: we normalize by (max(N-1,1) * max_amount) to keep budget within [0,1].
    """
    if max_amount <= 0 or actual_delta_steps <= 0:
        return
    denom = max((n - 1) * max_amount, 1)
    used = float(abs(actual_delta_steps)) / float(denom)
    decay_state["budget"] = max(0.0, decay_state.get("budget", 1.0) - used)

class ShuffleTagsAdvanced:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"default": ""}),
                "separator": ("STRING", {"default": ","}),  # use ", " if your input uses spaced commas
                "shuffle_amount_low": ("INT", {"default": 0, "min": 0, "max": 999}),
                "shuffle_amount_high": ("INT", {"default": 10, "min": 0, "max": 999}),
                "mode": (["WALK", "WALK_FORWARD", "WALK_BACKWARD", "JUMP"],),
                "algorithm": (["RANDOM", "LINEAR_IN", "LINEAR_OUT", "SHUFFLE_DECAY", "SHUFFLE_DECAY_REVERSE"],),
                "limit": ("INT", {"default": 0, "min": 0, "max": 1000000}),  # 0 = unlimited shuffles
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("shuffled_string",)
    FUNCTION = "shuffleAdvanced"
    CATEGORY = "Custom Nodes"

    def shuffleAdvanced(self,
                        string: str,
                        separator: str,
                        shuffle_amount_low: int,
                        shuffle_amount_high: int,
                        mode: str,
                        algorithm: str,
                        limit: int,
                        seed: int) -> Tuple[str]:
        """
        Progressive, seedable, direction-aware shuffling for prompt tags.

        Notes / origins:
        - random.Random(seed): stdlib deterministic RNG
        - list.insert()/pop(): stdlib list ops; we avoid moving if target == current
        - LIMIT: counts actual moves performed (not output length)
        - No whitespace trimming: tokens are exactly as split by `separator`
        """
        rng = random.Random(seed)

        # Preserve tokens exactly as authored; do NOT strip whitespace or drop empties.
        tokens = string.split(separator)
        n = len(tokens)
        if n <= 1:
            return (string,)

        low = max(0, int(shuffle_amount_low))
        high = max(low, int(shuffle_amount_high))
        mode = mode.upper()
        algorithm = algorithm.upper()

        # Working list keeps (orig_index, token) so we can find items stably.
        working: List[Tuple[int, str]] = list(enumerate(tokens))

        # Order of processing: reverse only for SHUFFLE_DECAY_REVERSE
        if algorithm == "SHUFFLE_DECAY_REVERSE":
            order_indices = list(reversed(range(n)))
        else:
            order_indices = list(range(n))

        # Global decay state for SHUFFLE_DECAY variants
        decay_state = {"budget": 1.0}

        shuffles_done = 0  # LIMIT counts actual moves only

        for j, i in enumerate(order_indices):
            if limit > 0 and shuffles_done >= limit:
                break  # stop performing shuffles; keep remaining order intact

            # Progress goes 0→1 along the chosen processing order
            progress = 0.0 if n <= 1 else (j / (n - 1))
            strength = _compute_strength(progress, algorithm, rng, decay_state)
            step_budget = int(round(_lerp(low, high, strength)))

            # Find current position of original index i
            cur_pos = next(idx for idx, pair in enumerate(working) if pair[0] == i)

            # Decide target position per mode
            if mode == "JUMP":
                if rng.random() < strength:
                    target_pos = rng.randrange(len(working))
                else:
                    delta = rng.randint(0, step_budget)
                    direction = rng.choice((-1, 1))
                    target_pos = _clamp(cur_pos + direction * delta, 0, len(working) - 1)
            elif mode == "WALK_FORWARD":
                delta = rng.randint(0, step_budget)
                target_pos = _clamp(cur_pos + delta, 0, len(working) - 1)
            elif mode == "WALK_BACKWARD":
                delta = rng.randint(0, step_budget)
                target_pos = _clamp(cur_pos - delta, 0, len(working) - 1)
            else:  # WALK
                delta = rng.randint(0, step_budget)
                direction = rng.choice((-1, 1))
                target_pos = _clamp(cur_pos + direction * delta, 0, len(working) - 1)

            # Count only actual moves; apply decay based on actual distance moved.
            actual_delta = abs(target_pos - cur_pos)
            _apply_decay(actual_delta_steps=actual_delta, max_amount=high, n=n, decay_state=decay_state)

            if actual_delta == 0:
                continue  # no move, no shuffle counted

            # Perform the move
            item = working.pop(cur_pos)
            # After pop, list is shorter; keep target within bounds of new length.
            target_pos = _clamp(target_pos, 0, len(working))
            working.insert(target_pos, item)
            shuffles_done += 1

        final_tokens = [t for _, t in working]
        shuffled_string = separator.join(final_tokens)
        return (shuffled_string,)

class CleanupTags:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING",),
                "cleanup_commas": ("BOOLEAN", {"default": True, "tooltip": "cleans up extra commas if there is no tag present between them"}),
                "cleanup_whitespace": ("BOOLEAN", {"default": True, "tooltip": "cleans up leading/trailing whitespace, then excessive whitespace"}),
                "remove_lora_tags": ("BOOLEAN", {"default": False, "tooltip": "completely removes lora tags from the string"}),
                "cleanup_newlines": (["FALSE", "SPACE", "COMMA"], {"default": "FALSE", "tooltip": "replaces newlines (\\n) with a space or comma"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "Custom"

    @staticmethod
    def process(string, cleanup_commas, cleanup_newlines, cleanup_whitespace, remove_lora_tags):
        # Stage 1: Remove LoRA tags
        if remove_lora_tags:
            string = re.sub(LORA_PATTERN, "", string)

        # Stage 2: Replace newlines with space
        if cleanup_newlines == "SPACE":
            string = string.replace("\n", " ")
        elif cleanup_newlines == "COMMA":
            string = string.replace("\n", ", ")

        # Stage 3: Remove empty comma sections
        if cleanup_commas:
            # Iteratively remove leading commas
            while re.match(r"^[ \t]*,[ \t]*", string):
                string = re.sub(r"^[ \t]*,[ \t]*", "", string)

            # Iteratively remove trailing commas
            while re.search(r"[ \t]*,[ \t]*$", string):
                string = re.sub(r"[ \t]*,[ \t]*$", "", string)

            # Remove empty comma sections inside the string
            while re.search(r",[ \t]*,", string):
                string = re.sub(r",[ \t]*,", ",", string)

        # Stage 4: Whitespace cleanup
        if cleanup_whitespace:
            # Trim only spaces/tabs around the whole string
            string = string.strip(" \t")

            # Collapse repeating spaces/tabs into one
            string = re.sub(r"[ \t]{2,}", " ", string)

            # Normalize spacing around commas: "x ,  y" → "x, y"
            string = re.sub(r"[ \t]*,[ \t]*", ", ", string)

        return (string,)


class StringAppend4:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string_1": ("STRING", {"default": ""}),
                "string_2": ("STRING", {"default": ""}),
                "string_3": ("STRING", {"default": ""}),
                "string_4": ("STRING", {"default": ""}),
                "combine_mode": (["NONE", "SPACE", "NEWLINE"], {"default": "NONE"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "merge_strings"
    CATEGORY = "Custom"

    @staticmethod
    def merge_strings(string_1, string_2, string_3, string_4, combine_mode):
        # Extract all strings in order
        strings = [string_1, string_2, string_3, string_4]
        # Filter out empty strings
        strings = [s for s in strings if s.strip() != ""]
        # Join with newline
        if combine_mode == "SPACE":
            connector = " "
        elif combine_mode =="NEWLINE":
            connector = "\n"
        else:
            connector = ""
        merged = connector.join(strings)
        return (merged,)


class StringAppend8:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string_1": ("STRING", {"default": ""}),
                "string_2": ("STRING", {"default": ""}),
                "string_3": ("STRING", {"default": ""}),
                "string_4": ("STRING", {"default": ""}),
                "string_5": ("STRING", {"default": ""}),
                "string_6": ("STRING", {"default": ""}),
                "string_7": ("STRING", {"default": ""}),
                "string_8": ("STRING", {"default": ""}),
                "combine_mode": (["NONE", "SPACE", "NEWLINE"], {"default": "NONE"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "merge_strings"
    CATEGORY = "Custom"

    @staticmethod
    def merge_strings(string_1, string_2, string_3, string_4, string_5, string_6, string_7, string_8, combine_mode):
        # Extract all strings in order
        strings = [string_1, string_2, string_3, string_4, string_5, string_6, string_7, string_8]
        # Filter out empty strings
        strings = [s for s in strings if s.strip() != ""]
        # Join with newline
        if combine_mode == "SPACE":
            connector = " "
        elif combine_mode =="NEWLINE":
            connector = "\n"
        else:
            connector = ""
        merged = connector.join(strings)
        return (merged,)
    


class LoraTagNormalizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "total_weight": ("FLOAT", {"default": 1.0, "min": 0.0}),
                "bounds": (["POSITIVE", "NEGATIVE", "BOTH"], {"default": "BOTH"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "normalize"
    CATEGORY = "utils"

    def normalize(self, string: str, total_weight: float, bounds: str):
        """
        Normalize <lora:name:weight> tags.

        - Parses float weights; leaves tags with non-float weights untouched.
        - Ignores zero weights entirely.
        - BOUNDS controls which tags participate:
          POSITIVE: only >0
          NEGATIVE: only <0
          BOTH: all (magnitudes normalized, sign preserved)
        - Multiplies normalized proportions by total_weight.
        - Rounds output to 3 decimal places.
        """
        pattern = re.compile(r"<lora:([^:>]+):([^>]+)>")
        matches = list(pattern.finditer(string))

        # Collect parseable, non-zero lora entries
        entries = []
        for m in matches:
            full = m.group(0)
            name = m.group(1)
            raw_weight = m.group(2).strip()
            try:
                w = float(raw_weight)
            except Exception:
                # leave unparseable tags unchanged
                continue
            if w == 0.0:
                # explicitly ignore zero-weight tags
                continue
            entries.append({"full": full, "name": name, "weight": w})

        # nothing to normalize
        if not entries:
            return (string,)

        # Build normalized mapping keyed by the original full tag string
        normalized_map = {}

        if bounds == "POSITIVE":
            positives = [e for e in entries if e["weight"] > 0]
            total_pos = sum(e["weight"] for e in positives)
            if total_pos == 0:
                return (string,)
            for e in positives:
                new_val = (e["weight"] / total_pos) * total_weight
                normalized_map[e["full"]] = f"<lora:{e['name']}:{new_val:.3f}>"

        elif bounds == "NEGATIVE":
            negatives = [e for e in entries if e["weight"] < 0]
            total_neg_abs = sum(abs(e["weight"]) for e in negatives)
            if total_neg_abs == 0:
                return (string,)
            for e in negatives:
                # preserve negative sign while distributing by magnitude
                new_val = (e["weight"] / total_neg_abs) * total_weight
                normalized_map[e["full"]] = f"<lora:{e['name']}:{new_val:.3f}>"

        else:  # BOTH
            total_abs = sum(abs(e["weight"]) for e in entries)
            if total_abs == 0:
                return (string,)
            for e in entries:
                mag = (abs(e["weight"]) / total_abs) * total_weight
                sign = 1.0 if e["weight"] > 0 else -1.0
                new_val = mag * sign
                normalized_map[e["full"]] = f"<lora:{e['name']}:{new_val:.3f}>"

        # Replace tags using the original matched text as the key.
        def repl(m):
            orig = m.group(0)
            return normalized_map.get(orig, orig)

        new_string = pattern.sub(repl, string)
        return (new_string,)