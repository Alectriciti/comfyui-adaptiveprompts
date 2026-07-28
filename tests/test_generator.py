"""
Regression tests for py/generator.py prompt parsing and resolution.

Run from the repository root:
    py -3 -m unittest discover -s tests -p "test_*.py" -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

# Allow importing py.* without ComfyUI installed.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from py.generator import (  # noqa: E402
    FILE_PATTERN,
    SeededRandom,
    _extract_choice_weight,
    _find_top_level_separators,
    _parse_weighted_options,
    _protect_escaped_wildcards,
    _restore_escaped_wildcards,
    _split_top_level_pipes,
    evaluate_prompt_core,
    find_next_bracket_span,
    is_file_wildcard,
    resolve_wildcard_path,
    resolve_wildcards,
    sequence_prompt_elements,
)


class WildcardDirTestCase(unittest.TestCase):
    """Shared temp wildcards directory for integration-style parser tests."""

    wildcard_dir: str

    @classmethod
    def setUpClass(cls):
        cls.wildcard_dir = tempfile.mkdtemp(prefix="adaptive_prompts_test_")
        cls._write("fruit.txt", "apple\nbanana\norange\n")
        cls._write("and.txt", "and\nwith\n")
        cls._write("pick.txt", "one\ntwo\nthree\n")
        cls._write("chance.txt", "%80% common\n%10% uncommon\nrare\n")
        cls._write("nested/a.txt", "nested_a\n")
        cls._write("nested/b.txt", "nested_b\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.wildcard_dir, ignore_errors=True)

    @classmethod
    def _write(cls, relative_path: str, content: str) -> None:
        path = os.path.join(cls.wildcard_dir, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _rng(self, seed: int = 42, mode: str = "Legacy") -> SeededRandom:
        return SeededRandom(seed, mode=mode)

    def _resolve(self, prompt: str, seed: int = 42, mode: str = "Legacy", **kwargs) -> str:
        return resolve_wildcards(
            prompt,
            self._rng(seed, mode),
            self.wildcard_dir,
            **kwargs,
        )

    def _evaluate(self, prompt: str, seed: int = 42, mode: str = "Legacy", **kwargs) -> str:
        resolved_vars = kwargs.pop("_resolved_vars", {})
        hide_comments = kwargs.pop("hide_comments", True)
        return evaluate_prompt_core(
            prompt,
            self._rng(seed, mode),
            self.wildcard_dir,
            resolved_vars,
            hide_comments=hide_comments,
            **kwargs,
        )


class TestParserHelpers(unittest.TestCase):
    def test_split_top_level_pipes_respects_nested_braces(self):
        self.assertEqual(_split_top_level_pipes("a|{x|y}|b"), ["a", "{x|y}", "b"])

    def test_find_top_level_separators(self):
        self.assertEqual(_find_top_level_separators("2$$ and $$a|b"), [(1, "$$"), (8, "$$")])

    def test_extract_choice_weight(self):
        self.assertEqual(_extract_choice_weight("option%1.5"), ("option", 1.5))
        self.assertEqual(_extract_choice_weight("plain"), ("plain", 1.0))

    def test_extract_choice_weight_ignores_nested_percent(self):
        """Regression for issue #10: trailing weight must not come from nested brackets."""
        self.assertEqual(
            _extract_choice_weight("{%7|cover image%3}%4"),
            ("{%7|cover image%3}", 4.0),
        )
        self.assertEqual(_extract_choice_weight("{%7|cover image%3}"), ("{%7|cover image%3}", 1.0))

    def test_parse_weighted_options(self):
        lines = StringIO("# comment\n%80% common\n%10% uncommon\nrare\n")
        items, weights = _parse_weighted_options(lines)
        self.assertEqual(items, ["common", "uncommon", "rare"])
        self.assertEqual(weights, [80.0, 10.0, 1.0])

    def test_is_file_wildcard(self):
        self.assertTrue(is_file_wildcard("__fruit__"))
        self.assertTrue(is_file_wildcard("__fruit^color__"))
        self.assertTrue(is_file_wildcard("__^color__"))
        self.assertFalse(is_file_wildcard("not_a_wildcard"))

    def test_find_next_bracket_span_returns_innermost_outer_span(self):
        span = find_next_bracket_span("prefix {a|b} suffix")
        self.assertEqual(span, (7, 11))

    def test_escaped_wildcard_protect_and_restore(self):
        mapping: dict[str, str] = {}
        protected = _protect_escaped_wildcards(r"keep \__fruit__ literal", mapping)
        self.assertNotIn("__fruit__", protected)
        restored = _restore_escaped_wildcards(protected, mapping)
        # Restore returns the literal token without the leading escape backslash.
        self.assertEqual(restored, "keep __fruit__ literal")


class TestBracketResolution(WildcardDirTestCase):
    def test_simple_bracket_choice_is_deterministic(self):
        self.assertEqual(self._resolve("{red|green|blue}", seed=0), "blue")
        self.assertEqual(self._resolve("{red|green|blue}", seed=42), "green")
        self.assertEqual(self._resolve("{red|green|blue}", seed=100), "red")

    def test_multi_pick_deck_syntax(self):
        self.assertEqual(self._resolve("{2$$a|b|c}", seed=5), "a, b")

    def test_dynamic_separator_wildcard(self):
        self.assertEqual(
            self._resolve("{2$$ and $$apple|banana|cherry}", seed=3),
            "banana and cherry",
        )

    def test_nested_bracket_inside_choice(self):
        self.assertEqual(self._resolve("{before {x|y} after|plain}", seed=1), "before y after")


class TestWildcardResolution(WildcardDirTestCase):
    def test_file_wildcard_is_deterministic(self):
        self.assertEqual(self._resolve("__fruit__", seed=0), "orange")
        self.assertEqual(self._resolve("__fruit__", seed=42), "banana")

    def test_missing_wildcard_injects_warning_by_default(self):
        with redirect_stdout(StringIO()):
            result = self._resolve("__does_not_exist__")
        self.assertEqual(result, '!!!WILDCARD "does_not_exist" NOT FOUND!!!')

    def test_nested_folder_glob(self):
        result = self._resolve("__nested/*__", seed=0)
        self.assertIn(result, {"nested_a", "nested_b"})

    def test_adjacent_wildcards_both_resolve(self):
        result = self._resolve("__fruit__ and __fruit__", seed=7)
        parts = result.split(" and ")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0])
        self.assertTrue(parts[1])

    def test_chinese_filename_wildcard(self):
        """Regression for issue #9: non-ASCII wildcard filenames must resolve."""
        self._write("good中文.txt", "fine\n")
        token = "__good中文__"
        match = FILE_PATTERN.search(token)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "good中文")

        rng = self._rng(0, "Legacy")
        filepath = resolve_wildcard_path("good中文", rng.next_rng(), self.wildcard_dir, None)
        self.assertTrue(filepath and os.path.exists(filepath))
        self.assertEqual(self._resolve(token, seed=0), "fine")


class TestEscapingAndSpecialTokens(WildcardDirTestCase):
    def test_backslash_escaped_wildcard_is_preserved(self):
        self.assertEqual(
            self._resolve(r"literal \__fruit__ end"),
            "literal __fruit__ end",
        )

    def test_lora_tag_with_double_underscores(self):
        """Regression lock for lora-name handling (see README for intended preservation).

        Underscore pairs inside lora names are still parsed as wildcards. With the
        default Inject Warning setting, a missing token is marked in-place instead of
        collapsing the surrounding lora tag structure.
        """
        prompt = "<lora:coolest__lora__ever__:1.0>"
        with redirect_stdout(StringIO()):
            result = self._resolve(prompt)
        self.assertEqual(
            result,
            '<lora:coolest!!!WILDCARD "lora" NOT FOUND!!!ever__:1.0>',
        )


class TestCommentsAndVariables(WildcardDirTestCase):
    def test_comment_blocks_are_removed_from_output(self):
        result = self._evaluate("## hidden ## visible", hide_comments=True)
        self.assertEqual(result.strip(), "visible")

    def test_comment_block_assigns_variables_for_later_use(self):
        result = self._evaluate("## __fruit^x__ ## hello __^x__", seed=1)
        self.assertEqual(result.strip(), "hello apple")

    def test_variable_assignment_on_wildcard(self):
        resolved_vars: dict = {}
        self._resolve("__fruit^slot__", seed=4, _resolved_vars=resolved_vars)
        recall = self._resolve("__^slot__", seed=4, _resolved_vars=resolved_vars)
        self.assertEqual(recall, resolved_vars["slot"]["fruit"])


class TestRngModes(WildcardDirTestCase):
    def test_adaptive_mode_is_stable_for_same_wildcard_identity(self):
        adaptive_a = self._resolve("before __pick__ after", seed=99, mode="Adaptive")
        adaptive_b = self._resolve("other __pick__", seed=99, mode="Adaptive")
        adaptive_c = self._resolve("__pick__", seed=99, mode="Adaptive")
        self.assertEqual(adaptive_a, "before one after")
        self.assertEqual(adaptive_b, "other one")
        self.assertEqual(adaptive_c, "one")

    def test_legacy_mode_can_differ_from_adaptive_for_same_seed(self):
        legacy = self._resolve("__pick__", seed=99, mode="Legacy")
        adaptive = self._resolve("__pick__", seed=99, mode="Adaptive")
        self.assertEqual(legacy, "two")
        self.assertEqual(adaptive, "one")


class TestSequencer(WildcardDirTestCase):
    def test_sequence_prompt_elements_parallel_mode(self):
        prompt = "__fruit__ and {red|green|blue}"
        rng = self._rng(3, "Legacy")
        resolved_vars: dict = {}
        result = sequence_prompt_elements(
            prompt,
            seed=3,
            mode="PARALLEL",
            wildcard_dir=self.wildcard_dir,
            _resolved_vars=resolved_vars,
            rng=rng,
        )
        self.assertEqual(result, "apple and red")


class TestWeightedWildcards(WildcardDirTestCase):
    def test_weighted_wildcard_draws_known_values(self):
        outcomes = {self._resolve("__chance__", seed=i) for i in range(100)}
        self.assertTrue(outcomes.issubset({"common", "uncommon", "rare"}))
        self.assertIn("common", outcomes)


if __name__ == "__main__":
    unittest.main()
