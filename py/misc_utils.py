import random
import re

from typing import Tuple
from comfy.comfy_types import ComfyNodeABC, InputTypeDict
from typing import List


from comfy.cli_args import args

class ScaledSeedGenerator(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls) -> InputTypeDict:
        return {
            "required": {
                "seed": ("INT", {"default": 30000, "min": 0, "max": 2**63-1, "step": 1, "tooltip":"The Base seed - Every other seed is ultimately controlled by this one.\nE.G. A rate of 0.5 will change the seed every 2 increments."}),
                "rate_a": ("FLOAT", {"default": 1.0, "min": 0.001, "max": 1.0, "step": 0.025}),
                "rate_b": ("FLOAT", {"default": 1.0, "min": 0.001, "max": 1.0, "step": 0.025}),
                "rate_c": ("FLOAT", {"default": 0.5, "min": 0.001, "max": 1.0, "step": 0.025}),
                "rate_d": ("FLOAT", {"default": 0.125, "min": 0.001, "max": 1.0, "step": 0.025}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT")
    RETURN_NAMES = ("Output A", "Output B", "Output C", "Output D")
    FUNCTION = "generate"
    CATEGORY = "adaptiveprompts/utils"

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
        return rng.randint(0, 2**63 - 1)

    def generate(self, seed: int, rate_a: float, rate_b: float, rate_c: float, rate_d: float):
        random_a = self._scaled_random(seed, rate_a)
        random_b = self._scaled_random(seed+1, rate_b)
        random_c = self._scaled_random(seed+2, rate_c)
        random_d = self._scaled_random(seed+3, rate_d)

        return (random_a, random_b, random_c, random_d)
    



class TagCounter(ComfyNodeABC):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "string": ("STRING", {"default": ""})
            }
        }

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("tag_count",)
    FUNCTION = "count_tags"
    CATEGORY = "adaptiveprompts/utils"

    def count_tags(self, string: str) -> Tuple[int]:
        # Split by commas and count non-empty stripped elements
        tags = [s.strip() for s in string.split(",") if s.strip()]
        return (len(tags),)

# full parse: <lora:name:weight>
LORA_FULL_PATTERN = re.compile(r"<lora:([^:>]+):([^>]+)>")

class LoraTagNormalizer:
    @classmethod
    def INPUT_TYPES(cls) -> InputTypeDict:
        return {
            "required": {
                "string": ("STRING", {"multiline": True, "default": ""}),
                "target_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "tooltip": "Desired total weight (renamed from total_weight)."}),
                "bounds": (["POSITIVE", "NEGATIVE", "BOTH"], {"default": "BOTH", "tooltip": "Which lora tags participate: POSITIVE only >0, NEGATIVE only <0, BOTH uses magnitudes and preserves sign."}),
                "mode": (
                    ["NORMALIZE", "LIMITER", "SOFT_COMPRESS", "HARD_COMPRESS"],
                    {
                        "default": "NORMALIZE",
                        "tooltip": (
                            "Mode of operation:\n"
                            "NORMALIZE — always scale selected tags so their combined magnitude equals target_weight.\n"
                            "LIMITER — if combined magnitude <= target_weight do nothing; otherwise normalize down to target_weight (hard cap).\n"
                            "SOFT_COMPRESS — gentle compressor (approx. 1:2 style). If sum > target_weight, reduce values using a soft curve (keeps sum > target but much smaller than original).\n"
                            "HARD_COMPRESS — stronger compressor (approx. 1:5 style). Uses the same algorithm as SOFT_COMPRESS but with stronger settings."
                        ),
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "normalize"
    CATEGORY = "adaptiveprompts/utils"

    # ---------- helpers ----------

    @staticmethod
    def _parse_loras(text: str):
        """Return list of parsed entries (full_tag, name, weight_float) for parseable tags."""
        matches = list(LORA_FULL_PATTERN.finditer(text))
        entries = []
        for m in matches:
            full = m.group(0)
            name = m.group(1)
            raw_weight = m.group(2).strip()
            try:
                weight = float(raw_weight)
            except Exception:
                # leave unparseable tags alone
                continue
            if weight == 0.0:
                # ignore explicit zeros
                continue
            entries.append({"full": full, "name": name, "weight": weight})
        return entries

    @staticmethod
    def _format_tag(name: str, value: float) -> str:
        # round to 3 decimals as requested
        return f"<lora:{name}:{value:.3f}>"

    @staticmethod
    def _safe_sum_abs(values: List[float]) -> float:
        return sum(abs(v) for v in values)

    @staticmethod
    def _compress_magnitudes(magnitudes: List[float], target: float, ratio: float) -> List[float]:
        """
        Compressor that:
          - Shapes per-entry magnitudes using a mild exponent (so larger inputs are reduced more).
          - Then applies a global reduction factor so the final total is reduced relative to the original,
            controlled by `ratio` (ratio > 1 means stronger compression).
        Implementation notes / rationale:
          - exponent p = 1 / (1 + (ratio-1)/4) maps ratio=2 -> p~0.8 (gentle), ratio=5 -> p~0.5 (stronger).
          - global_strength s = (ratio-1)/ratio maps ratio to (0..1) and is used to compute reduction factor
            factor = 1 / (1 + (total/target - 1) * s)
            * when s==1 this becomes exact normalization (factor = target/total)
            * when s<1 the result will be between original total and normalized total (i.e. a softer cap)
        """
        if not magnitudes:
            return []

        total = sum(magnitudes)
        # if not over target, no compression needed
        if total <= target or target <= 0.0:
            return magnitudes.copy()

        # exponent to shape large values down (p in (0,1])
        p = 1.0 / (1.0 + (ratio - 1.0) / 4.0)
        shaped = [m ** p for m in magnitudes]
        sum_shaped = sum(shaped)
        if sum_shaped == 0:
            # degenerate case
            return magnitudes.copy()

        # global factor: s in (0..1) where larger s -> stronger reduction (s->1 -> normalization)
        s = (ratio - 1.0) / ratio
        factor = 1.0 / (1.0 + (total / target - 1.0) * s)

        # desired total after compression (will be > target if s < 1, == target if s == 1)
        desired_total = total * factor

        # convert shaped distribution back to magnitudes that sum to desired_total
        new_mags = [(shaped_i / sum_shaped) * desired_total for shaped_i in shaped]
        return new_mags

    @staticmethod
    def _normalize_magnitudes(magnitudes: List[float], target: float) -> List[float]:
        """Normalize magnitudes so they sum to target. If total is 0, return unchanged list."""
        total = sum(magnitudes)
        if total == 0.0:
            return magnitudes.copy()
        factor = target / total
        return [m * factor for m in magnitudes]

    # ---------- main function ----------

    def normalize(self, string: str, target_weight: float, bounds: str, mode: str):
        """
        Normalize/compress/limit <lora:name:weight> tags.

        Behavior summary:
          - Parses tags with float weights; leaves tags with non-float weights unchanged.
          - Ignores zero-weight tags entirely.
          - 'bounds' selects which tags are affected: POSITIVE, NEGATIVE, BOTH.
          - 'mode' selects processing:
              NORMALIZE: always re-scale selected tags so their total magnitude == target_weight.
              LIMITER: only normalize when selected total magnitude > target_weight.
              SOFT_COMPRESS: gentle compressor (approx 1:2), reduces totals but may still exceed target.
              HARD_COMPRESS: stronger compressor (approx 1:5).
          - Rounds output weights to 3 decimal places.
        """
        entries = self._parse_loras(string)
        if not entries:
            return (string,)

        # Which entries will we process according to bounds?
        if bounds == "POSITIVE":
            entries_to_process = [e for e in entries if e["weight"] > 0]
        elif bounds == "NEGATIVE":
            entries_to_process = [e for e in entries if e["weight"] < 0]
        else:  # BOTH
            entries_to_process = entries.copy()

        if not entries_to_process:
            # nothing to change for selected bound
            return (string,)

        # Prepare magnitudes and original sign mapping
        signs = [1.0 if e["weight"] >= 0 else -1.0 for e in entries_to_process]
        mags = [abs(e["weight"]) for e in entries_to_process]
        total_mags = sum(mags)
        if total_mags == 0.0:
            return (string,)

        # Decide new magnitudes based on mode
        new_mags = None
        mode_upper = (mode or "").upper()
        if mode_upper == "NORMALIZE":
            new_mags = self._normalize_magnitudes(mags, target_weight)

        elif mode_upper == "LIMITER":
            # Only act when sum > target
            if total_mags <= target_weight:
                # keep original values unchanged
                new_mags = mags.copy()
            else:
                new_mags = self._normalize_magnitudes(mags, target_weight)

        elif mode_upper == "SOFT_COMPRESS":
            # gentle compressor; ratio ~2
            new_mags = self._compress_magnitudes(mags, target_weight, ratio=2.0)

        elif mode_upper == "HARD_COMPRESS":
            # stronger compressor; ratio ~5
            new_mags = self._compress_magnitudes(mags, target_weight, ratio=5.0)

        else:
            # unknown mode -> default to normalize
            new_mags = self._normalize_magnitudes(mags, target_weight)

        # now build replacement map for the exact original full tags we parsed (only for processed entries)
        normalized_map = {}
        # iterate over processed entries and their computed new magnitudes
        for e, sign, nm in zip(entries_to_process, signs, new_mags):
            new_val_signed = nm * sign
            normalized_map[e["full"]] = self._format_tag(e["name"], new_val_signed)

        # perform replacement using the full-pattern so unparsed/unprocessed tags stay as-is
        def repl(m):
            orig = m.group(0)
            return normalized_map.get(orig, orig)

        new_string = LORA_FULL_PATTERN.sub(repl, string)
        return (new_string,)