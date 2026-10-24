"""Marketplace page 2 skills: b-roll library matching, carousel, render review, VHS look, clean voice.
Run:  python -m unittest discover tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor import extras, extras2, style  # noqa: E402
from editor.config import find_tool  # noqa: E402
from editor.render import build_filtergraph  # noqa: E402


def _have_ffmpeg():
    try:
        subprocess.run([find_tool("ffmpeg"), "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class GraphTests(unittest.TestCase):
    def test_vhs_and_clean_voice(self):
        g = build_filtergraph([(0.0, 2.0)], True, None, True, size=(360, 640),
                              style={"look": "vhs", "voice_clean": True})
        self.assertIn("rgbashift", g)
        self.assertIn("afftdn", g)
        plain = build_filtergraph([(0.0, 2.0)], True, None, True, size=(360, 640), style={})
        self.assertNotIn("afftdn", plain)
        self.assertNotIn("rgbashift", plain)

    def test_style_keys(self):
        self.assertEqual(style.clean_style({"look": "vhs", "voice_clean": True}), {"look": "vhs", "voice_clean": True})

    def test_export_names(self):
        self.assertTrue(extras.safe_export_name("carousel_3.png"))
        self.assertFalse(extras.safe_export_name("../x.png"))


class MatchTests(unittest.TestCase):
    def test_each_clip_used_once_and_ids_checked(self):
        words = [{"i": i, "text": t, "start": i, "end": i + 0.5} for i, t in enumerate("a clock ticks by the sea".split())]
        plan = {"broll": [{"id": "m1", "from_word": 0, "to_word": 2, "show": "clock"},
                          {"id": "m2", "from_word": 3, "to_word": 5, "show": "sea"}]}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "library.json").write_text(json.dumps([
                {"file": "lib_a.mp4", "thumb": "lib_a.jpg", "desc": "clock", "duration": 4, "has_audio": False},
                {"file": "lib_b.mp4", "thumb": "lib_b.jpg", "desc": "sea", "duration": 5, "has_audio": True}]))
            reply = {"matches": [{"moment": "m1", "clip": 0}, {"moment": "m2", "clip": 0}, {"moment": "m2", "clip": 1},
                                 {"moment": "zz", "clip": 1}, {"moment": "m1", "clip": 7}]}
            with mock.patch.object(extras2, "chat_json", return_value=reply):
                out = extras2.match_library(d, {"words": words}, plan)
        self.assertEqual([(m["moment"], m["clip"]) for m in out], [("m1", "lib_a.mp4"), ("m2", "lib_b.mp4")])


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg not found")
class CarouselTests(unittest.TestCase):
    def test_carousel_pngs(self):
        ff = find_tool("ffmpeg")
        words = [{"i": i, "text": t, "start": 0.3 + i * 0.4, "end": 0.6 + i * 0.4} for i, t in enumerate("Edit three times faster today".split())]
        tr = {"duration": 3.0, "words": words, "segments": []}
        plan = {"cuts": [], "duration": 3.0, "removed_words": []}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = d / "in.mp4"
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=25:d=3",
                            "-pix_fmt", "yuv420p", str(src)], check=True)
            reply = {"slides": [{"title": "Edit faster", "body": "Cut every pause."}, {"title": "Comment EDIT", "body": "Guide."}]}
            with mock.patch.object(extras2, "chat_json", return_value=reply):
                names = extras2.carousel(d, src, tr, plan, style.DEFAULTS, "Arial")
            self.assertEqual(names, ["carousel_1.png", "carousel_2.png"])
            from editor.media import probe
            info = probe(d / "exports" / "carousel_1.png")
            self.assertEqual((info.width, info.height), (1080, 1350))


if __name__ == "__main__":
    unittest.main()
