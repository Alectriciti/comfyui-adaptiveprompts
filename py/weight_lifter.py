import re
import math
from .generator import SeededRandom


class WeightLifter:
    """
    🏋🏼 Weight Lifter - Apply systematic or random weights to tags.

    Modes:
      - RANDOM: Independent random weights in [min,max]. Randomly selects which tags to modify.
      - GRADIENT: Evenly spaced selection across tags; weights progress smoothly min→max.
      - BURST: Selects clusters of tags around random centers; stronger near centers.
      - NOISE: Randomly selected tags; smooth low-pass noise mapped to the selected order.

    Keyword handling:
      - NONE: No keyword rules.
      - ONLY: Only modify keywords.
      - IGNORE: Skip keywords.
      - BOOST: Force keywords near max_weight (± keyword_variance).
      - SUPPRESS: Force non-keywords near min_weight (± keyword_variance).

    Existing tag behavior:
      - PRESERVE: Never change tags that already have explicit weights.
      - MODIFY: Add delta (proposed - 1.0) to an existing weight.
      - OVERWRITE: Replace existing weight with the proposed weight.

    Notes:
      - Whitespace/newlines preserved exactly.
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
                "existing_tag_behavior": (["PRESERVE", "MODIFY", "OVERWRITE"], {"default": "PRESERVE"}),
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
        return [(x - mn) / (mx - mn) for x in seq] if mx > mn else [0.5] * n

    def _rand_sample(self, rng, items, k):
        """Sample k distinct items without replacement using RNG (deterministic)."""
        if k >= len(items): return list(items)
        decorated = [(rng.random(), it) for it in items]
        decorated.sort(key=lambda x: x[0])
        return [it for _, it in decorated[:k]]

    def _evenly_spaced_positions(self, N, k):
        """Return k unique integer positions in [0, N-1], spread as evenly as possible."""
        if k >= N: return list(range(N))
        if k <= 1: return [N // 2]
        # Use rounding on linspace-like positions
        pos = [int(round(i * (N - 1) / (k - 1))) for i in range(k)]
        # Dedup while preserving relative spread; if duplicates, fill gaps
        out, used = [], set()
        for p in pos:
            if p not in used:
                out.append(p); used.add(p)
        # Fill if we lost some to dedup
        if len(out) < k:
            # insert closest missing positions
            for i in range(N):
                if i not in used:
                    out.append(i); used.add(i)
                    if len(out) == k: break
        out.sort()
        return out

    def _select_indices(self, rng, eligible, mode, limit):
        """
        Select which eligible indices to modify based on mode.
        Returns (selected_indices_sorted, aux) where aux may carry burst params.
        """
        if not eligible:
            return [], {}

        N = len(eligible)
        k = N if (not limit or limit <= 0) else min(limit, N)

        if k == N:
            return list(eligible), {}

        # Map into positions [0..N-1] for selection logic, then translate back.
        pos_all = list(range(N))

        if mode in ("RANDOM", "NOISE"):
            pos_sel = self._rand_sample(rng, pos_all, k)
            pos_sel.sort()
            return [eligible[p] for p in pos_sel], {}

        if mode == "GRADIENT":
            pos_sel = self._evenly_spaced_positions(N, k)
            return [eligible[p] for p in pos_sel], {}

        if mode == "BURST":
            # clustered selection: choose 1–3 centers, then pick around them
            centers_count = int(round(1 + rng.random() * 2))  # 1..3
            centers_count = max(1, min(3, centers_count))
            centers = self._rand_sample(rng, pos_all, centers_count)
            centers.sort()

            # window size scales with N and target k
            window = max(1, int(round(max(N * 0.08, k * 0.6 / max(1, centers_count)))))

            pos_sel_set = set()
            # round-robin expanding around centers
            while len(pos_sel_set) < k:
                for c in centers:
                    if len(pos_sel_set) >= k: break
                    # pick an offset near the center
                    offset = int(round(rng.uniform(-window, window)))
                    p = self._clamp(c + offset, 0, N - 1)
                    pos_sel_set.add(p)
                # safety: if saturated with few options, random backfill
                if len(pos_sel_set) < k and len(pos_sel_set) == len(set(pos_sel_set)):
                    pos_sel_set |= set(self._rand_sample(rng, pos_all, k - len(pos_sel_set)))

            pos_sel = sorted(pos_sel_set)
            aux = {"centers": centers, "window": window, "N": N}
            return [eligible[p] for p in pos_sel], aux

        # Fallback: RANDOM
        pos_sel = self._rand_sample(rng, pos_all, k)
        pos_sel.sort()
        return [eligible[p] for p in pos_sel], {}

    # ----------------- main -----------------

    def process(self, prompt, seed, min_weight, max_weight, delimiter, mode,
                existing_tag_behavior, limit, keyword_selection, keyword_mode,
                keyword_variance, jitter_strength):

        rng = SeededRandom(seed)
        parts = re.split(f"({re.escape(delimiter)})", prompt) if delimiter else [prompt]
        kws = self._parse_keywords(keyword_selection)

        # Collect eligible tag indices (even positions in parts)
        eligible = []
        meta = {}  # index -> dict(meta)
        for i in range(0, len(parts), 2):
            seg = parts[i]
            inner = re.match(r'^\(\s*(.*?)\s*\)$', seg.strip())
            body = inner.group(1) if inner else seg.strip()
            if not body:
                continue

            # parse existing explicit weight, if any
            m_w = re.match(r'^(.*?)(?::\s*([0-9]*\.?[0-9]+))$', body)
            text = m_w.group(1) if m_w else body
            existing = float(m_w.group(2)) if m_w else None

            # Keyword eligibility
            is_kw = self._is_keyword(text, kws) if kws else False
            if keyword_mode == "ONLY" and not is_kw:
                continue
            if keyword_mode == "IGNORE" and is_kw:
                continue

            # Existing tag behavior gating
            if existing is not None and existing_tag_behavior == "PRESERVE":
                # do not modify existing weighted tags in PRESERVE mode
                continue

            eligible.append(i)
            meta[i] = {
                "raw_seg": seg,
                "has_paren": inner is not None,
                "text": text,
                "existing": existing,
                "is_kw": is_kw,
            }

        # Pre-select which eligible tags to modify based on the mode
        selected, aux = self._select_indices(rng, eligible, mode, limit)
        total = len(selected)

        # Precompute sequences for structured modes over the ORDERED selection
        # We'll use the order of 'selected' as they appear in the original prompt.
        baseline = self._baseline(min_weight, max_weight)

        noise_seq = self._smooth_noise(rng, total) if (mode == "NOISE" and total > 0) else None
        # For BURST, we already have centers/window in aux (computed in selection)

        # Build a map index -> rank among selected (0..total-1) for gradient/noise
        rank_map = {idx: r for r, idx in enumerate(selected)}

        # Compose output with modifications only on selected indices
        results = []
        for i, seg in enumerate(parts):
            if delimiter and i % 2 == 1:
                results.append(seg)
                continue

            if i not in meta or i not in rank_map:
                # Not selected (or ineligible) -> keep original
                results.append(seg)
                continue

            info = meta[i]
            text = info["text"]
            existing = info["existing"]
            is_kw = info["is_kw"]

            # Proposed weight (before existing_tag_behavior application)
            # Start with a base around the baseline (used by BURST's shape).
            base = self._clamp(existing if (existing is not None and existing_tag_behavior == "PRESERVE") else baseline,
                               min_weight, max_weight)

            # mode-specific proposal
            if mode == "RANDOM":
                w = rng.uniform(min_weight, max_weight)

            elif mode == "GRADIENT":
                r = rank_map[i]
                t = (r / (total - 1)) if total > 1 else 0.0
                w = min_weight + t * (max_weight - min_weight)

            elif mode == "NOISE":
                r = rank_map[i]
                s = noise_seq[r] if noise_seq else 0.5
                w = min_weight + s * (max_weight - min_weight)

            elif mode == "BURST":
                # Weight bump around nearest cluster center over eligible positions.
                # Recompute relative position of this index among the eligible list.
                # We need its position (0..N-1)
                if "N" in aux and "centers" in aux and "window" in aux:
                    # Locate this index's position among eligible
                    N = aux["N"]
                    centers = aux["centers"]
                    window = max(1, aux["window"])
                    # Build a quick lookup: position in eligible list
                    # (Do a simple index lookup; eligible is small relative to prompt)
                    pos = next((p for p, idx in enumerate(eligible) if idx == i), 0)
                    # distance from nearest center (in positions)
                    d = min(abs(pos - c) for c in centers) if centers else 0
                    s = math.exp(- (d / float(window)) ** 2)  # 1.0 at center, fades outward
                    w = base + (rng.uniform(-1, 1) * (max_weight - min_weight) * s)
                else:
                    # Fallback if aux missing
                    w = rng.uniform(min_weight, max_weight)

            else:
                w = base

            # Optional jitter (applied before keyword shaping)
            if jitter_strength > 0:
                w += rng.uniform(-1, 1) * (max_weight - min_weight) * jitter_strength

            # Keyword shaping
            if keyword_mode == "BOOST" and is_kw:
                w = max_weight + rng.uniform(-keyword_variance, keyword_variance)
            elif keyword_mode == "SUPPRESS" and not is_kw:
                w = min_weight - rng.uniform(0, keyword_variance)

            # Apply existing_tag_behavior
            if existing is not None:
                if existing_tag_behavior == "PRESERVE":
                    # Shouldn't happen because PRESERVE excluded existing-weighted from selection,
                    # but keep the guard to be safe.
                    new_w = existing
                elif existing_tag_behavior == "MODIFY":
                    delta = w - 1.0
                    new_w = existing + delta
                else:  # OVERWRITE
                    new_w = w
            else:
                new_w = w

            new_w = self._clamp(new_w, 0.0, 10.0)
            w_str = self._fmt_weight(new_w)
            results.append(f"({text}:{w_str})")

        return ("".join(results),)
