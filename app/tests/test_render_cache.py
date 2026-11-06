"""Render speed-ups and time-range corrections (reel studio)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
SCRIPTS = APP / "reel_agent" / "creator-reel" / "scripts"


class GradeLutTest(unittest.TestCase):
    def test_lut_matches_float_grade(self):
        try:
            import numpy as np
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("numpy / opencv not installed")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["REEL_CACHE"] = tmp
            sys.path.insert(0, str(SCRIPTS))
            import grade
            img = np.random.default_rng(1).integers(0, 256, (192, 108, 3), dtype=np.uint8)
            for vig in (True, False):
                a = grade.grade_slow(img, 0.9, vig, [-0.012, 0.03, -0.006]).astype(int)
                b = grade.grade(img, 0.9, vig, [-0.012, 0.03, -0.006]).astype(int)
                self.assertLessEqual(abs(a - b).max(), 1)
            os.environ.pop("REEL_CACHE", None)


class TimeRangeTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(APP))
        from editor import reel
        self.reel = reel

    def test_only_inside_range_survives(self):
        plan = {"beats": [{"type": "list", "from": 2, "to": 5}, {"type": "statement", "from": 30, "to": 32}],
                "accent": [3, 31], "cta": {"keyword": "X", "from": 40}}
        rev = {"fix": {"4": "ok", "31": "no"}, "cut_words": [3, 35], "beats_update": [{"index": 0, "fields": {"label": "A"}},
               {"index": 1, "fields": {"text": "B"}}], "beats_remove": [1], "set": {"accent": [4], "pace": "loose",
               "headline": {"l1": "h"}, "cta": {"keyword": "Y", "from": 40}}}
        rng = {"words": set(range(1, 7)), "t0": 1.0, "t1": 3.0, "dur": 30.0}
        skipped = self.reel.limit_revision(rev, plan, rng)
        self.assertEqual(rev["fix"], {"4": "ok"})
        self.assertEqual(rev["cut_words"], [3])
        self.assertEqual([u["index"] for u in rev["beats_update"]], [0])
        self.assertEqual(rev["beats_remove"], [])
        self.assertEqual(sorted(rev["set"]["accent"]), [4, 31])        # 3 (inside) replaced by 4, 31 kept
        self.assertIn("headline", rev["set"])                            # range is at the start
        self.assertNotIn("pace", rev["set"])
        self.assertNotIn("cta", rev["set"])
        self.assertTrue(skipped)

    def test_product_scenes_outside_range_untouched(self):
        plan = {"scenes": [{"from": 0, "to": 3, "text": "a"}, {"from": 3, "to": 9, "text": "b"}], "outro": {"name": "N"}}
        rev = {"scenes_update": [{"index": 0, "fields": {"text": "A"}}, {"index": 1, "fields": {"text": "B"}}],
               "set": {"outro": {"name": "M"}, "accent_color": "#000000"}}
        changes, skipped = self.reel.apply_product_revision(plan, rev, {1}, {"t0": 5, "t1": 6, "dur": 12})
        self.assertEqual([s["text"] for s in plan["scenes"]], ["a", "B"])
        self.assertEqual(plan["outro"], {"name": "N"})
        self.assertNotIn("accent_color", plan)
        self.assertTrue(skipped)


class StylesTest(unittest.TestCase):
    def test_every_style_has_its_files(self):
        import json
        for sid in ("talking_head", "product", "faceless"):
            d = APP / "reel_agent" / "styles" / sid
            for f in ("SKILL.md", "style.json", "planner.md"):
                self.assertTrue((d / f).exists(), d / f)
            json.loads((d / "style.json").read_text(encoding="utf-8"))
        json.loads((APP / "reel_agent" / "styles" / "product" / "plan_schema.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
