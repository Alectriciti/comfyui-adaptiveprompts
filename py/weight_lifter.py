import re
import math
from .generator import SeededRandom


class WeightLifter:
    """
    🏋🏼 Weight Lifter - Apply systematic or random weights to tags.

    Modes:
      - UNIFORM: All tags → same baseline.
      - RANDOM: Independent random weights in [min,max].
      - GRADIENT: Smooth progression across tags from min→max (or reversed).
      - BURST: A single strong bump of emphasis, fading outward.
      - NOISE: Smooth jittery variation (low-pass filtered random).

    Keyword handling:
      - NONE: No keyword rules.
      - ONLY: Only modify keywords.
      - IGNORE: Skip keywords.
      - BOOST: Force keywords near max_weight (± keyword_variance).
      - SUPPRESS: Force non-keywords near min_weight (± keyword_variance).

    Notes:
      - Whitespace/newlines preserved exactly.
      - Existing weights preserved if preserve_existing=True.
      - Baseline defaults to midpoint unless 1.0 is within [min,max].
    """

    DECIMAL_PLACES = 2

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "min_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 10.0, "step": 0.01}),
                "max_weight": ("FLOAT", {"default": 1.2, "min": 0.0, "max": 10.0, "step": 0.01}),
                "delimiter": ("STRING", {"default": ","}),
                "mode": ([
                    "RANDOM",
                    "GRADIENT",
                    "BURST",
                    "NOISE",
                ], {"default": "RANDOM"}),
                "preserve_existing": ("BOOLEAN", {"default": True}),
                "limit": ("INT", {"default": 0, "min": 0, "max": 999}),
                "keyword_selection": ("STRING", {"multiline": False, "default": ""}),
                "keyword_mode": (["NONE", "ONLY", "IGNORE", "BOOST", "SUPPRESS"], {"default": "NONE"}),
                "keyword_variance": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 5.0, "step": 0.01}),
                "jitter_strength": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01,
                                               "tooltip": "Extra randomness applied on top of structured modes."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "process"
    CATEGORY = "prompt"

    # ----------------- helpers -----------------

    def _clamp(self, v, lo, hi): return max(lo, min(hi, v))
    def _fmt_weight(self, w): return f"{w:.{self.DECIMAL_PLACES}f}"
    def _parse_keywords(self, text): return [k.strip() for k in text.split(",") if k.strip()]

    def _is_keyword(self, tag, kws):
        t = re.sub(r"\s+", " ", tag.lower()).replace("_", " ")
        return any(re.sub(r"\s+", " ", k.lower()).replace("_", " ") in t for k in kws)

    def _baseline(self, min_w, max_w): return 1.0 if min_w <= 1.0 <= max_w else (min_w + max_w) / 2.0

    def _smooth_noise(self, rng, n, alpha=0.25):
        if n <= 0: return []
        seq = [rng.random()]
        for _ in range(1, n):
            seq.append(alpha * rng.random() + (1 - alpha) * seq[-1])
        mn, mx = min(seq), max(seq)
        return [(x - mn) / (mx - mn) for x in seq] if mx > mn else [0.5]*n

    # ----------------- main -----------------

    def process(self, prompt, seed, min_weight, max_weight, delimiter, mode,
                preserve_existing, limit, keyword_selection, keyword_mode,
                keyword_variance, jitter_strength):
        rng = SeededRandom(seed)
        parts = re.split(f"({re.escape(delimiter)})", prompt) if delimiter else [prompt]
        kws = self._parse_keywords(keyword_selection)

        # collect eligible indices
        eligible = []
        for i in range(0, len(parts), 2):
            seg = parts[i]
            inner = re.match(r'^\(\s*(.*?)\s*\)$', seg.strip())
            body = inner.group(1) if inner else seg.strip()
            if not body: continue
            if preserve_existing and re.search(r':[0-9]', body): continue
            if kws:
                is_kw = self._is_keyword(body, kws)
                if keyword_mode == "ONLY" and not is_kw: continue
                if keyword_mode == "IGNORE" and is_kw: continue
            eligible.append(i)
        if limit: eligible = eligible[:limit]

        total = len(eligible)
        baseline = self._baseline(min_weight, max_weight)

        # Precompute curves
        noise_seq = self._smooth_noise(rng, total) if mode == "NOISE" else None
        burst_center = rng.uniform(0.25, 0.75) if mode == "BURST" else None

        results, applied = [], 0
        for i, seg in enumerate(parts):
            if delimiter and i % 2 == 1:
                results.append(seg); continue
            if i not in eligible:
                results.append(seg); continue

            raw = seg.strip()
            m_paren = re.match(r'^\(\s*(.*?)\s*\)$', raw)
            body = m_paren.group(1) if m_paren else raw
            m_w = re.match(r'^(.*?)(?::\s*([0-9]*\.?[0-9]+))$', body)
            text = m_w.group(1) if m_w else body
            existing = float(m_w.group(2)) if m_w else None
            kw = self._is_keyword(text, kws) if kws else False

            base = self._clamp(existing if existing and not preserve_existing else baseline,
                               min_weight, max_weight)

            t = applied / (total - 1) if total > 1 else 0
            if mode == "RANDOM":
                w = rng.uniform(min_weight, max_weight)
            elif mode == "GRADIENT":
                w = min_weight + t * (max_weight - min_weight)
            elif mode == "BURST":
                dist = abs(t - burst_center) / 0.15
                s = math.exp(-dist * dist)
                w = base + (rng.uniform(-1,1) * (max_weight - min_weight) * s)
            elif mode == "NOISE":
                s = noise_seq[applied]
                w = min_weight + s * (max_weight - min_weight)
            else:
                w = base

            if jitter_strength > 0:
                w += rng.uniform(-1,1) * (max_weight-min_weight) * jitter_strength

            if keyword_mode == "BOOST" and kw:
                w = max_weight + rng.uniform(-keyword_variance, keyword_variance)
            elif keyword_mode == "SUPPRESS" and not kw:
                w = min_weight - rng.uniform(0, keyword_variance)

            w = self._clamp(w, 0.0, 10.0)
            w_str = self._fmt_weight(w)
            results.append(f"({text}:{w_str})")
            applied += 1

        return ("".join(results),)
