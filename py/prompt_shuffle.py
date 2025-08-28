import random
from typing import List, Tuple

LORA_PATTERN = r"<lora:[^>]+>"


class PromptShuffle:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"default": ""}),
                "separator": ("STRING", {"multiline": True, "default": ","}),
                "limit": ("INT", {
                    "default": 0, "min": 0, "max": 200,
                    "tooltip": "Number of single-item moves to perform.\n0 = full shuffle (completely randomize order)."
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff})
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("shuffled_string",)
    FUNCTION = "shuffle_strings"
    CATEGORY = "adaptiveprompts/processing"

    def shuffle_strings(self, string: str, separator: str, limit: int, seed: int) -> Tuple[str]:
        """
        Shuffle by performing `limit` single-item moves (pop+insert).
        If limit == 0, perform a full shuffle of all items.
        Deterministic when seed != 0.
        """
        rng = random.Random(seed) if seed != 0 else random.Random()

        if separator == "":
            return (string,)

        parts = string.split(separator)
        n = len(parts)

        # Nothing to do for empty/one-item lists
        if n <= 1:
            return (string,)
        
        if limit <= 0:
            rng.shuffle(parts)
            return (separator.join(parts),)

        # `limit` move operations (pop src, insert at dest)
        moves_done = 0
        attempts = 0
        max_attempts = limit * 10 + 100  # safety cap to avoid loops

        while moves_done < limit and attempts < max_attempts:
            attempts += 1
            src = rng.randrange(n)
            dest = rng.randrange(n)
            if src == dest:
                continue  # pick a different target

            # pop and insert (adjust dest if pop occurred before dest)
            item = parts.pop(src)
            if src < dest:
                dest -= 1
            parts.insert(dest, item)

            moves_done += 1

        return (separator.join(parts),)




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

class PromptShuffleAdvanced:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"default": ""}),
                "separator": ("STRING", {"multiline": True, "default": ","}),  # use ", " if your input uses spaced commas
                "shuffle_amount_start": ("INT", {"default": 0, "min": 0, "max": 999}),
                "shuffle_amount_end": ("INT", {"default": 10, "min": 0, "max": 999}),
                "mode": (["WALK", "WALK_FORWARD", "WALK_BACKWARD", "JUMP"], {"tooltip":"WALK - Travels the tag step by step in a certain direction.\nJUMP - Randomizes the position completely"}),
                "algorithm": (["RANDOM", "LINEAR_IN", "LINEAR_OUT", "SHUFFLE_DECAY", "SHUFFLE_DECAY_REVERSE"],),
                "limit": ("INT", {"default": 0, "min": 0, "max": 1000000}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("shuffled_string",)
    FUNCTION = "shuffleAdvanced"
    CATEGORY = "adaptiveprompts/processing"

    def shuffleAdvanced(self,
                        string: str,
                        separator: str,
                        shuffle_amount_start: int,
                        shuffle_amount_end: int,
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

        low = max(0, int(shuffle_amount_start))
        high = max(low, int(shuffle_amount_end))
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
