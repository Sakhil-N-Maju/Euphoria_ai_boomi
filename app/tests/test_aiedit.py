"""AI edit tests. No network: the AI replies are faked. Run:  python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor import aiedit  # noqa: E402
from editor.llm import parse_json  # noqa: E402
from editor.plan import build_plan  # noqa: E402

SETTINGS = {"remove_silences": False, "min_silence": 0.6, "pad": 0.1, "min_cut": 0.25, "remove_fillers": True}


def make_transcript(texts, step=0.5):
    words = [{"i": i, "text": t, "start": i * step, "end": i * step + 0.4, "prob": 0.9} for i, t in enumerate(texts)]
    return {"duration": len(texts) * step + 0.5, "words": words,
            "segments": [{"start": 0.0, "end": len(texts) * step, "word_ids": [w["i"] for w in words]}]}


# "hello friends today we hello friends today we will talk about reels"
TR = make_transcript("hello friends today we hello friends today we will talk about reels".split())


class RetakeTests(unittest.TestCase):
    def test_valid_retake_is_kept(self):
        out = aiedit.validate_retakes([{"remove_from": 0, "remove_to": 3, "kept_from": 4, "kept_to": 11,
                                        "reason": "restarted intro"}], 12)
        self.assertEqual(out, [{"remove_from": 0, "remove_to": 3, "kept_from": 4, "kept_to": 11,
                                "reason": "restarted intro"}])

    def test_invalid_retakes_are_dropped(self):
        raw = [
            {"remove_from": 5, "remove_to": 3, "kept_from": 6, "kept_to": 7},     # reversed range
            {"remove_from": 0, "remove_to": 3, "kept_from": 2, "kept_to": 7},     # keep overlaps removal
            {"remove_from": 0, "remove_to": 3, "kept_from": 4, "kept_to": 99},    # word doesn't exist
            {"remove_from": "a", "remove_to": 3, "kept_from": 4, "kept_to": 5},   # not a number
            "nonsense",
        ]
        self.assertEqual(aiedit.validate_retakes(raw, 12), [])

    def test_overlapping_and_too_large_removals_dropped(self):
        raw = [{"remove_from": 0, "remove_to": 3, "kept_from": 4, "kept_to": 5},
               {"remove_from": 2, "remove_to": 4, "kept_from": 6, "kept_to": 7}]        # overlaps the first
        self.assertEqual(len(aiedit.validate_retakes(raw, 12)), 1)
        big = [{"remove_from": 0, "remove_to": 8, "kept_from": 9, "kept_to": 11}]       # 9 of 12 words > 50%
        self.assertEqual(aiedit.validate_retakes(big, 12), [])

    def test_find_retakes_uses_ai_reply(self):
        reply = {"retakes": [{"remove_from": 0, "remove_to": 3, "kept_from": 4, "kept_to": 11, "reason": "x"}]}
        with mock.patch.object(aiedit, "chat_json", return_value=reply) as fake:
            found = aiedit.find_retakes(TR)
        self.assertEqual(found[0]["remove_to"], 3)
        sent = fake.call_args[0][1][0]["content"]
        self.assertIn("0:hello", sent)
        self.assertIn("11:reels", sent)

    def test_plan_marks_retake_cuts(self):
        retakes = [{"remove_from": 1, "remove_to": 4, "kept_from": 5, "kept_to": 11, "reason": "x"}]
        plan = build_plan(TR, SETTINGS, [], removed_words=[1, 2, 3, 4], retakes=retakes)
        self.assertEqual(plan["retake_words"], [1, 2, 3, 4])
        self.assertEqual([c["reason"] for c in plan["cuts"]], ["retake"])


class ChatTests(unittest.TestCase):
    def test_listing_marks_cut_words(self):
        text = aiedit.transcript_listing(TR, {1})
        self.assertIn("~1:friends~", text)
        self.assertIn("2:today", text)

    def test_apply_cut_restore_keep_only(self):
        removed, s, c, notes = aiedit.apply_actions([
            {"type": "cut", "from": 0, "to": 3},
            {"type": "restore", "from": 2, "to": 2},
            {"type": "cut", "from": 50, "to": 60},
            {"type": "settings", "min_silence": 9, "remove_silences": True},
            {"type": "captions", "enabled": False},
            {"type": "explode"},
        ], set(), 12)
        self.assertEqual(removed, {0, 1, 3})
        self.assertEqual(s, {"remove_silences": True, "min_silence": 2.0})
        self.assertEqual(c, {"enabled": False})
        self.assertEqual(len(notes), 2)

        removed, *_ = aiedit.apply_actions([{"type": "keep_only", "ranges": [[4, 7]]}], {5}, 12)
        self.assertEqual(removed, {0, 1, 2, 3, 5, 8, 9, 10, 11})

    def test_never_cuts_everything(self):
        removed, _, _, notes = aiedit.apply_actions([{"type": "cut", "from": 0, "to": 11}], set(), 12)
        self.assertEqual(removed, set())
        self.assertIn("refused to cut every word", notes)

    def test_target_seconds(self):
        self.assertEqual(aiedit.target_seconds("make a 30-second reel"), 30)
        self.assertEqual(aiedit.target_seconds("under 1 min please"), 60)
        self.assertEqual(aiedit.target_seconds("45s version"), 45)
        self.assertIsNone(aiedit.target_seconds("remove the intro"))

    def test_chat_edit_retries_toward_target(self):
        tr = make_transcript([f"w{i}" for i in range(40)], step=1.0)   # 40 s of speech
        plan = build_plan(tr, SETTINGS, [])

        def rebuild(removed, settings, captions):
            return build_plan(tr, {**SETTINGS, **settings}, [], removed_words=sorted(removed),
                              captions=captions)

        first = {"reply": "Here is a reel.", "actions": [{"type": "keep_only", "ranges": [[0, 4]]}]}       # ~5 s
        second = {"reply": "Made it closer to 20 seconds.", "actions": [{"type": "restore", "from": 5, "to": 19}]}
        with mock.patch.object(aiedit, "chat_json", side_effect=[first, second]):
            new_plan, reply, _ = aiedit.chat_edit(tr, plan, "make a 20 second reel", [], rebuild)
        self.assertAlmostEqual(new_plan["edited_duration"], 20, delta=2)
        self.assertEqual(reply, "Made it closer to 20 seconds.")


class ParseTests(unittest.TestCase):
    def test_fenced_and_messy_json(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('Sure! {"a": [1, 2]} hope that helps'), {"a": [1, 2]})


if __name__ == "__main__":
    unittest.main()
