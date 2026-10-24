"""Finishing tests: style validation, keyword/topic picks, timeline, captions, b-roll prompts, sound, and a real
render with every option on (skipped if ffmpeg isn't available). Run:  python -m unittest discover tests"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor import broll, sfx, style, timeline  # noqa: E402
from editor.captions import caption_lines, write_ass  # noqa: E402
from editor.config import find_tool  # noqa: E402
from editor.plan import build_plan  # noqa: E402

SETTINGS = {"remove_silences": True, "min_silence": 0.6, "pad": 0.1, "min_cut": 0.25, "remove_fillers": True}
TEXT = "Hello friends. Today I save you twenty minutes. Now music. It is free and fast.".split()


def transcript(gap_after=(1, 7, 9), step=0.4):
    words, t = [], 0.3
    for i, w in enumerate(TEXT):
        words.append({"i": i, "text": w, "start": round(t, 3), "end": round(t + 0.3, 3), "prob": 0.9})
        t += step + (1.2 if i in gap_after else 0)
    return {"duration": round(t + 0.5, 3), "words": words,
            "segments": [{"start": 0.0, "end": t, "word_ids": list(range(len(words)))}]}


class StyleTests(unittest.TestCase):
    def test_clean_style_filters_and_clamps(self):
        out = style.clean_style({"pop_scale": 9, "look": "neon", "sfx": "yes", "title": "  A   b ",
                                 "keywords": [3, "4", -1, 99, "x"], "accent": "ff0000", "bogus": 1}, n_words=10)
        self.assertEqual(out, {"pop_scale": 1.6, "title": "A b", "keywords": [3, 4], "accent": "#FF0000"})

    def test_auto_keywords_prefer_numbers_and_claims(self):
        tr = transcript()
        kw = style.auto_keywords(tr["words"], set())
        texts = [tr["words"][i]["text"] for i in kw]
        self.assertIn("twenty", texts)
        self.assertTrue(all(b - a > 1 for a, b in zip(kw, kw[1:])))

    def test_auto_topic_breaks_after_long_pauses(self):
        tr = transcript()
        breaks = style.auto_topic_breaks(tr["words"], set(), edited_duration=60, spacing=2.0)
        self.assertIn(8, breaks)          # "Now" starts after "minutes." and a long pause


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.tr = transcript()
        self.plan = build_plan(self.tr, SETTINGS, [], style={"transitions": True, "topic_breaks": [8]},
                               broll=[{"id": "b1", "from_word": 3, "to_word": 6, "clip": "x.mp4", "clip_duration": 5.0,
                                       "layout": "full", "impact": True, "show": "clock"}])

    def test_transition_snaps_to_cut(self):
        ew = timeline.edited_words(self.tr, self.plan)
        trans = timeline.transition_times(ew, self.plan, style.clean_style(self.plan["style"]))
        self.assertEqual(len(trans), 1)
        self.assertTrue(any(abs(trans[0] - j) < 0.01 for j in timeline.joins(self.plan)))

    def test_broll_slot_is_2_to_4_seconds(self):
        ew = timeline.edited_words(self.tr, self.plan)
        slot = timeline.broll_slots(ew, self.plan, {"broll": {"min_seconds": 2, "max_seconds": 4}})["b1"]
        self.assertGreaterEqual(slot["end"] - slot["start"], 2.0 - 1e-6)
        self.assertLessEqual(slot["end"] - slot["start"], 4.0 + 1e-6)

    def test_sound_map_has_whoosh_and_hit(self):
        st = {**style.DEFAULTS, **self.plan["style"]}
        tl = timeline.describe(self.tr, self.plan, {"broll": {}}, st)
        kinds = [e["kind"] for e in tl["sound_map"]]
        self.assertIn("whoosh", kinds)
        self.assertIn("hit", kinds)


class CaptionTests(unittest.TestCase):
    def test_word_sync_and_pop_tags(self):
        tr = transcript()
        plan = build_plan(tr, SETTINGS, [])
        lines = caption_lines(tr, plan, {"max_words": 4, "max_chars": 26})
        st = {**style.DEFAULTS, "caption_style": "highlight", "keyword_pop": True, "keywords": [6],
              "title": "Edit Faster", "title_enabled": True}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.ass"
            write_ass(lines, (720, 1280), {"font": "Arial"}, p, style=st)
            text = p.read_text(encoding="utf-8-sig")
        self.assertIn("Style: Title", text)
        self.assertIn("Edit Faster", text)
        self.assertIn("\\t(0,150,0.5,\\fscx118\\fscy118)}twenty", text)
        self.assertGreater(text.count("Dialogue: 0,"), len(lines))   # one event per word, not per line


class BrollTests(unittest.TestCase):
    def test_prompt_formula_and_no_music_line(self):
        p = broll.compose_prompt("a steel tiffin box", "dropping onto a table", "in a Kerala kitchen", "drone",
                                 broll.DEFAULT_STYLE_PHRASE)
        self.assertTrue(p.startswith("A steel tiffin box, dropping onto a table, in a Kerala kitchen, static shot"))
        self.assertTrue(p.endswith(broll.NO_MUSIC))

    def test_validate_moments(self):
        words = transcript()["words"]
        raw = [{"from": 3, "to": 6, "subject": "a clock", "action": "ticking"},
               {"from": 5, "to": 8, "subject": "x", "action": "y"},          # overlaps the first
               {"from": 9, "to": 99, "subject": "x", "action": "y"},         # no such word
               {"from": 9, "to": 10, "subject": "", "action": "y"}]          # no subject
        out = broll.validate_moments(raw, words, set(), 5)
        self.assertEqual([(m["from_word"], m["to_word"]) for m in out], [(3, 6)])


class SoundTests(unittest.TestCase):
    def test_effects_are_finite_and_short(self):
        for kind in ("whoosh", "whoosh_soft", "pop", "tick", "hit"):
            y = sfx.effect(kind, style.DEFAULTS)
            self.assertTrue(0 < len(y) < sfx.SR)
            self.assertAlmostEqual(float(max(abs(y))), 1.0, places=3)

    def test_duck_envelope_levels(self):
        env = sfx.duck_envelope(sfx.SR * 4, [(1.0, 3.0)], -10, 8)
        to_db = lambda x: 20 * __import__("math").log10(x)  # noqa: E731
        self.assertAlmostEqual(to_db(env[int(0.2 * sfx.SR)]), -10, places=1)
        self.assertAlmostEqual(to_db(env[int(2.0 * sfx.SR)]), -18, places=1)


def _have_ffmpeg() -> bool:
    try:
        subprocess.run([find_tool("ffmpeg"), "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg not found")
class RenderTests(unittest.TestCase):
    """Real renders of a generated 6-second clip, landscape and portrait, with every option on."""

    def _render(self, w, h, layout, look, draft, extra=None):
        from editor.media import probe
        from editor.render import render
        ff = find_tool("ffmpeg")
        tr = transcript(step=0.3)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=25:d={tr['duration']}",
                            "-f", "lavfi", "-i", f"sine=f=220:d={tr['duration']}", "-shortest", "-pix_fmt", "yuv420p",
                            str(d / "input.mp4")], check=True)
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "smptebars=s=640x360:r=30:d=5",
                            "-f", "lavfi", "-i", "anoisesrc=d=5:a=0.2", "-shortest", "-pix_fmt", "yuv420p",
                            str(d / "broll_b1.mp4")], check=True)
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=330:d=3",
                            str(d / "music.wav")], check=True)
            st = {"title": "Edit Faster", "title_enabled": True, "caption_style": "highlight", "keyword_pop": True,
                  "keywords": [6], "transitions": True, "topic_breaks": [8], "punch_in": True, "look": look,
                  "sfx": True, "music": True, **(extra or {})}
            plan = build_plan(tr, SETTINGS, [], style=st, broll=[
                {"id": "b1", "from_word": 3, "to_word": 6, "clip": "broll_b1.mp4", "clip_duration": 5.0,
                 "clip_has_audio": True, "layout": layout, "impact": True, "show": "bars"}])
            out = d / "out.mp4"
            render(d, d / "input.mp4", tr, plan, out, draft=draft)
            info = probe(out)
            self.assertTrue(info.has_audio)
            self.assertAlmostEqual(info.duration, plan["edited_duration"], delta=0.25)
            self.assertTrue((d / "bed.wav").exists())
            return info

    def test_portrait_split_film_look_draft(self):
        info = self._render(360, 640, "split", "archival", draft=True)
        self.assertEqual((info.width, info.height), (360, 640))   # already below the draft size: no upscaling

    def test_landscape_full_film_look_everything(self):
        info = self._render(640, 360, "full", "archival_all", draft=False)
        self.assertEqual((info.width, info.height), (640, 360))

    def test_reel_from_landscape_with_grade_and_cta(self):
        info = self._render(640, 360, "split", "clean", draft=True,
                            extra={"format": "reel", "grade": "cinematic", "cta_keyword": "GUIDE", "face_x": 0.3})
        self.assertEqual((info.width, info.height), (540, 960))

    def test_landscape_split(self):
        self._render(640, 360, "split", "clean", draft=False)


if __name__ == "__main__":
    unittest.main()
