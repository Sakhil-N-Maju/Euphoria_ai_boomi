"""Run with:  python -m unittest discover tests   (from the app folder)"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor.plan import build_plan, keep_segments, normalize_word, remap_time  # noqa: E402

SETTINGS = {"remove_silences": True, "min_silence": 0.6, "pad": 0.1, "min_cut": 0.25, "remove_fillers": True}


def words(*items):
    return [{"i": i, "text": t, "start": s, "end": e, "prob": 0.9} for i, (t, s, e) in enumerate(items)]


class PlanTests(unittest.TestCase):
    def test_lead_tail_and_long_pause_cut(self):
        tr = {"duration": 10.0, "words": words(("hello", 1.0, 1.4), ("there", 1.5, 1.9), ("friends", 4.0, 4.5))}
        plan = build_plan(tr, SETTINGS, [])
        cuts = [(c["start"], c["end"]) for c in plan["cuts"]]
        self.assertEqual(cuts, [(0.0, 0.9), (2.0, 3.9), (4.6, 10.0)])
        self.assertAlmostEqual(plan["edited_duration"], (2.0 - 0.9) + (4.6 - 3.9), places=3)

    def test_short_pause_kept(self):
        tr = {"duration": 2.0, "words": words(("a", 0.1, 0.5), ("b", 0.9, 1.3))}
        plan = build_plan(tr, {**SETTINGS, "min_cut": 0.5}, [])
        self.assertEqual([c for c in plan["cuts"] if 0.5 < c["start"] < 0.9], [])

    def test_filler_removed_between_words(self):
        tr = {"duration": 3.0, "words": words(("so", 0.0, 0.4), ("um,", 0.45, 0.9), ("yes", 0.95, 1.3))}
        plan = build_plan(tr, {**SETTINGS, "remove_silences": False}, ["um"])
        self.assertEqual(plan["filler_words"], [1])
        self.assertEqual(plan["removed_words"], [1])
        self.assertEqual(len(plan["cuts"]), 1)
        c = plan["cuts"][0]
        self.assertLessEqual(c["start"], 0.45)
        self.assertGreaterEqual(c["end"], 0.9)
        self.assertEqual(c["reason"], "filler")

    def test_user_restores_filler(self):
        tr = {"duration": 3.0, "words": words(("so", 0.0, 0.4), ("um", 0.45, 0.9), ("yes", 0.95, 1.3))}
        plan = build_plan(tr, {**SETTINGS, "remove_silences": False}, ["um"], removed_words=[])
        self.assertEqual(plan["cuts"], [])

    def test_never_cuts_everything(self):
        tr = {"duration": 3.0, "words": words(("a", 0.0, 0.4), ("b", 1.0, 1.4))}
        plan = build_plan(tr, SETTINGS, [], removed_words=[0, 1])
        self.assertEqual(plan["cuts"], [])

    def test_indic_normalization_keeps_vowel_signs(self):
        self.assertEqual(normalize_word("ഉം,"), "ഉം")
        self.assertEqual(normalize_word("हम्म।"), "हम्म")
        self.assertEqual(normalize_word("Umm!"), "umm")

    def test_remap(self):
        segs = keep_segments([{"start": 1.0, "end": 2.0, "reason": "x"}], 5.0)
        self.assertEqual(segs, [(0.0, 1.0), (2.0, 5.0)])
        self.assertAlmostEqual(remap_time(2.5, segs), 1.5)
        self.assertIsNone(remap_time(1.5, segs))


if __name__ == "__main__":
    unittest.main()
