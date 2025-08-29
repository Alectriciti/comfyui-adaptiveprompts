import re
import math
from typing import List, Tuple
from .generator import SeededRandom


class PromptMix:
    """
    Prompt Mix - sprinkle tokens from a 'mix' prompt into a base prompt.

    Inputs:
      - prompt_base: main prompt to modify
      - prompt_mix: secondary prompt providing tokens to insert
      - keep_first: number of initial base tokens to preserve (no insertions before them)
      - shuffle_mix_in: controls ordering of the mix tokens *after* insertion positions are chosen
          * False: assign mix tokens to the chosen positions sequentially (original order)
          * True:  assign mix tokens to the chosen positions in randomized order (seeded)
      - mode: how insertion slots are chosen (SPRINKLE, RANDOM, RANDOM_EXPONENTIAL, RANDOM_SQRT, RANDOM_MIDDLE)
      - seed: deterministic 64-bit integer seed
      - delimiter: token delimiter (default ',')
    """

    @classmethod
    def INPUT_TYPES(cls):
        mode_tip = (
            "Insertion distribution mode:\n"
            "- SPRINKLE: spread mix tokens evenly, avoiding adjacency where possible.\n"
            "- RANDOM: choose insertion slots uniformly at random (with replacement).\n"
            "- RANDOM_EXPONENTIAL: probability increases toward the end (exponential).\n"
            "- RANDOM_SQRT: probability grows like sqrt toward the end.\n"
            "- RANDOM_MIDDLE: probability peaks near the middle of the prompt."
        )
        return {
            "required": {
                "prompt_base": ("STRING", {"multiline": True, "default": "", "tooltip": "Original prompt (comma separated by default)."}),
                "prompt_mix": ("STRING", {"multiline": True, "default": "", "tooltip": "Prompt to mix into the base."}),
                "keep_first": ("INT", {"default": 0, "min": 0, "tooltip": "Number of first base sections to protect from mixing."}),
                "shuffle_mix_in": ("BOOLEAN", {"default": False, "tooltip": "If true, randomize *which* mix tokens fill the chosen positions."}),
                "mode": (["SPRINKLE", "RANDOM", "RANDOM_EXPONENTIAL", "RANDOM_SQRT", "RANDOM_MIDDLE"], {"default": "SPRINKLE", "tooltip": mode_tip}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "tooltip": "Deterministic seed (0 allowed)."}),
                "delimiter": ("STRING", {"default": ",", "tooltip": "Delimiter used to split/join tokens (default ',')."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "mix"
    CATEGORY = "prompt"

    # ---------------- helpers ----------------

    @staticmethod
    def _trim_token(tok: str) -> str:
        return tok.strip()

    @staticmethod
    def _normalize_for_match(tok: str) -> str:
        # collapse whitespace, lower-case for matching / duplication checks
        return re.sub(r"\s+", " ", tok.strip()).lower()

    @staticmethod
    def _joiner_from_base(base: str, delimiter: str) -> str:
        # If base uses delimiter + space anywhere, preserve that formatting
        if (delimiter + " ") in base:
            return delimiter + " "
        return delimiter

    @staticmethod
    def _weighted_slot_weights(S: int, mode: str) -> List[float]:
        if S <= 0:
            return [1.0]
        if S == 1:
            return [1.0]

        weights = []
        for j in range(S):
            t = j / (S - 1) if S > 1 else 0.0  # 0..1
            if mode == "RANDOM" or mode == "SPRINKLE":
                w = 1.0
            elif mode == "RANDOM_EXPONENTIAL":
                # exponential emphasizing later positions
                w = math.exp(3.0 * t)
            elif mode == "RANDOM_SQRT":
                w = math.sqrt(t) if t > 0 else 0.0
            elif mode == "RANDOM_MIDDLE":
                # triangular peak in center
                w = 1.0 - abs(2.0 * t - 1.0)
            else:
                w = 1.0
            weights.append(float(w))
        total = sum(weights)
        if total <= 0:
            return [1.0] * S
        return [w / total for w in weights]

    def _choose_slots(self, rng, k: int, S: int, mode: str) -> List[int]:
        """
        Choose a sequence of slot indices (length k) within [0..S-1].
        - SPRINKLE: attempt to produce k distinct, well-spaced slots (if possible).
        - Otherwise: sample with replacement by weighted distribution.
        """
        if k <= 0:
            return []

        # If there's only one slot, simply return slot 0 repeated k times
        if S <= 1:
            return [0] * k

        # SPRINKLE: aim for even spacing (unique slots when k <= S)
        if mode == "SPRINKLE":
            if k <= S:
                chosen_slots: List[int] = []
                # ideal spacing between chosen slots (we use k+1 to place in-between)
                spacing = S / (k + 1)
                jitter = max(0, int(math.floor(spacing / 2)))
                for i in range(k):
                    base = int((i + 1) * spacing)  # base index candidate
                    low = max(0, base - jitter)
                    high = min(S - 1, base + jitter)
                    chosen = None

                    # try multiple random draws preferring non-adjacency
                    for _ in range(40):
                        cand = rng.randint(low, high)
                        if all(abs(cand - s) > 1 for s in chosen_slots):
                            chosen = cand
                            break

                    # fallback to any unused in window
                    if chosen is None:
                        for cand in range(low, high + 1):
                            if cand not in chosen_slots and all(abs(cand - s) > 1 for s in chosen_slots):
                                chosen = cand
                                break

                    # fallback to any unused in window (drop adjacency constraint)
                    if chosen is None:
                        for cand in range(low, high + 1):
                            if cand not in chosen_slots:
                                chosen = cand
                                break

                    # fallback to nearest free slot searching outward
                    if chosen is None:
                        for delta in range(0, S):
                            for cand in (base - delta, base + delta):
                                if 0 <= cand < S and cand not in chosen_slots:
                                    chosen = cand
                                    break
                            if chosen is not None:
                                break

                    # as last resort pick any random slot not already taken
                    if chosen is None:
                        attempts = 0
                        while True:
                            cand = rng.randrange(0, S)
                            if cand not in chosen_slots or attempts > 20:
                                chosen = cand
                                break
                            attempts += 1

                    chosen_slots.append(chosen)

                return chosen_slots

            else:
                # k > S: get a good distribution for the first S (unique), then add random extras
                base_unique = self._choose_slots(rng, S, S, "SPRINKLE")
                extras = [rng.randrange(0, S) for _ in range(k - S)]
                return base_unique + extras

        # For weighted/random modes: sample with replacement using weights
        weights = self._weighted_slot_weights(S, mode)
        population = list(range(S))
        # rng.choices exists on random.Random
        return [rng.choices(population, weights=weights, k=1)[0] for _ in range(k)]

    # ---------------- core ----------------

    def mix(self,
            prompt_base: str,
            prompt_mix: str,
            keep_first: int,
            shuffle_mix_in: bool,
            mode: str,
            seed: int,
            delimiter: str = ",") -> Tuple[str]:

        seeded = SeededRandom(seed)
        rng = seeded.next_rng()

        # Split tokens, trimming around delimiter
        if delimiter == "":
            base_tokens = [prompt_base] if prompt_base else []
            mix_tokens = [prompt_mix] if prompt_mix else []
        else:
            # split trimming whitespace around delim to canonicalize tokens
            base_tokens = [self._trim_token(t) for t in re.split(rf'\s*{re.escape(delimiter)}\s*', prompt_base) if t is not None and t != ""]
            mix_tokens = [self._trim_token(t) for t in re.split(rf'\s*{re.escape(delimiter)}\s*', prompt_mix) if t is not None and t != ""]

        # Nothing to do
        if not mix_tokens:
            return (prompt_base,)

        joiner = self._joiner_from_base(prompt_base, delimiter)

        # Remove duplicate mix tokens that already appear in base (normalized)
        base_norm_set = set(self._normalize_for_match(t) for t in base_tokens)
        seen = set()
        filtered_mix = []
        for t in mix_tokens:
            norm = self._normalize_for_match(t)
            if not norm or norm in base_norm_set or norm in seen:
                continue
            seen.add(norm)
            filtered_mix.append(t)

        if not filtered_mix:
            return (prompt_base,)

        n = len(base_tokens)

        # Cap keep_first to [0, n]
        keep_first = max(0, min(keep_first, n))

        # Number of insertion slots available from keep_first .. end (append-at-end included)
        S = max(1, n - keep_first + 1)

        k = len(filtered_mix)

        # 1) CHOOSE positions (slot indices in 0..S-1) for each mix token
        chosen_slots = self._choose_slots(rng, k, S, mode)

        # 2) ASSIGN tokens to positions
        slots: List[List[str]] = [[] for _ in range(S)]

        if shuffle_mix_in:
            # Randomize token ordering then insert in the order of chosen_slots
            assigned_tokens = filtered_mix[:]
            rng.shuffle(assigned_tokens)
            for slot_idx, tok in zip(chosen_slots, assigned_tokens):
                slots[slot_idx].append(tok)

        else:
            # Preserve mix order. Assign tokens to chosen slots in ascending slot index order
            # so the relative order of tokens in the final prompt remains the same.
            # We pair the first mix token with the smallest chosen slot, second with second-smallest, etc.
            order_indices = sorted(range(len(chosen_slots)), key=lambda i: chosen_slots[i])
            for tok, idxpos in zip(filtered_mix, order_indices):
                slot_idx = chosen_slots[idxpos]
                slots[slot_idx].append(tok)

        # 3) BUILD result
        out_tokens: List[str] = []
        # iterate through positions 0..n for insertion slots and tokens
        for i in range(0, n + 1):
            slot_rel = i - keep_first
            if 0 <= slot_rel < S:
                out_tokens.extend(slots[slot_rel])
            if i < n:
                out_tokens.append(base_tokens[i])

        result = joiner.join(out_tokens) if out_tokens else prompt_base
        return (result,)
