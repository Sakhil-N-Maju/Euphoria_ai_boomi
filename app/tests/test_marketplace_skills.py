"""Marketplace skills: caption fixes, translation, subtitle files, lower-third, speed, shorts, post kit, exports.
Run:  python -m unittest discover tests   (no network: AI replies are faked; renders skip without ffmpeg)"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor import extras, style  # noqa: E402
from editor.captions import caption_lines, write_ass  # noqa: E402
from editor.config import find_tool  # noqa: E402
from editor.plan import build_plan  # noqa: E402
from editor.render import build_filtergraph  # noqa: E402

TEXT = "Hello friends. Today I edit with clod code. It saves twenty minutes. Try it free today.".split()
SETTINGS = {"remove_silences": True, "min_silence": 0.6, "pad": 0.1, "min_cut": 0.25, "remove_fillers": True}


def transcript(step=0.4):
    words = [{"i": i, "text": w, "start": round(0.3 + i * step, 3), "end": round(0.3 + i * step + 0.3, 3), "prob": 0.9}
             for i, w in enumerate(TEXT)]
    return {"duration": round(0.3 + len(TEXT) * step + 0.5, 3), "words": words,
            "segments": [{"start": 0.0, "end": len(TEXT) * step, "word_ids": list(range(len(TEXT)))}]}


def _have_ffmpeg():
    try:
        subprocess.run([find_tool("ffmpeg"), "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class CaptionFixTests(unittest.TestCase):
    def test_fixes_are_validated_and_applied(self):
        tr = transcript()
        reply = {"fixes": [{"id": 6, "text": "Claude"}, {"id": 99, "text": "x"}, {"id": 2, "text": "Today"},
                           {"id": 7, "text": ""}, {"id": 7, "text": "Code."}]}
        with mock.patch.object(extras, "chat_json", return_value=reply):
            fixes = extras.fix_words(tr)
        self.assertEqual([(f["id"], f["text"]) for f in fixes], [(6, "Claude"), (7, "Code.")])
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            out = extras.apply_fixes(d, tr, fixes)
            self.assertEqual(out["words"][6]["orig_text"], "clod")
            back = extras.restore_words(d)
            self.assertEqual(back["words"][6]["text"], "clod")
            self.assertFalse((d / "transcript.orig.json").exists())


class SubtitleTests(unittest.TestCase):
    def test_srt_vtt_with_speed_and_translation(self):
        tr = transcript()
        plan = build_plan(tr, SETTINGS, [])
        lines = caption_lines(tr, plan, {"max_words": 4, "max_chars": 26})
        srt = extras.subtitles(lines, "srt", speed=2.0, translations={lines[0]["text"]: "Namaskaram"}, dual=True)
        first = srt.split("\n\n")[0].split("\n")
        self.assertEqual(first[0], "1")
        self.assertRegex(first[1], r"^\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}$")
        self.assertEqual(first[3], "Namaskaram")
        vtt = extras.subtitles(lines, "vtt")
        self.assertTrue(vtt.startswith("WEBVTT"))

    def test_translate_uses_cache(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
                extras, "chat_json", side_effect=lambda s, m: {"lines": ["T:" + x for x in json.loads(m[-1]["content"])["lines"]]}) as fake:
            out = extras.translate_lines(Path(d), ["a", "b", "a"], "en")
            self.assertEqual(out, {"a": "T:a", "b": "T:b"})
            extras.translate_lines(Path(d), ["a", "b"], "en")
            self.assertEqual(fake.call_count, 1)          # second time everything came from the cache

    def test_lower_third_and_dual_lines_in_ass(self):
        tr = transcript()
        plan = build_plan(tr, SETTINGS, [])
        lines = caption_lines(tr, plan, {"max_words": 4, "max_chars": 26})
        st = {**style.DEFAULTS, "lower_name": "Nima Fathima", "lower_role": "Team Euphoria", "caption_lang": "en",
              "caption_dual": True}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.ass"
            write_ass(lines, (1080, 1920), {"font": "Arial"}, p, style=st, duration=10,
                      translations={ln["text"]: "EN " + ln["text"] for ln in lines})
            text = p.read_text(encoding="utf-8-sig")
        self.assertIn("LowerName,,0,0,0,,{\\move(", text)
        self.assertIn("Team Euphoria", text)
        self.assertEqual(text.count(",Trans,,"), len(lines))


class SpeedTests(unittest.TestCase):
    def test_speed_stage_added(self):
        g = build_filtergraph([(0.0, 2.0), (3.0, 5.0)], True, None, True, size=(320, 240), speed=1.25)
        self.assertIn("[vpre]setpts=PTS/1.250[vout]", g)
        self.assertIn("[apre]atempo=1.250[aout]", g)
        self.assertNotIn("setpts=PTS/", build_filtergraph([(0.0, 2.0)], True, None, True, size=(320, 240)))


class ShortsAndPostTests(unittest.TestCase):
    def test_find_shorts_validation(self):
        tr = transcript(step=2.0)                       # 16 words over ~32 s
        plan = build_plan(tr, {**SETTINGS, "remove_silences": False}, [])
        reply = {"clips": [{"title": "A", "from": 0, "to": 9}, {"title": "overlap", "from": 5, "to": 12},
                           {"title": "too short", "from": 14, "to": 15}, {"title": "bad", "from": 3, "to": 99}]}
        with mock.patch.object(extras, "chat_json", return_value=reply):
            clips = extras.find_shorts(tr, plan)
        self.assertEqual([c["title"] for c in clips], ["A"])

    def test_post_kit_chapters_use_real_times(self):
        tr = transcript(step=5.0)                       # ~80 s so chapters are allowed
        plan = build_plan(tr, {**SETTINGS, "remove_silences": False}, [])
        reply = {"instagram_caption": "Edit faster", "hashtags": ["editing"], "youtube_titles": ["T"],
                 "youtube_description": "D", "chapters": [{"word_id": 3, "title": "Intro"},
                                                          {"word_id": 6, "title": "Claude"},
                                                          {"word_id": 11, "title": "Free"}],
                 "thumbnail_text": ["3x"], "linkedin_post": "L"}
        with mock.patch.object(extras, "chat_json", return_value=reply):
            md = extras.post_kit(tr, plan, style.DEFAULTS, "talk.mp4")
        self.assertIn("0:00 Intro", md)                  # first chapter forced to 0:00
        self.assertIn("#editing", md)
        self.assertRegex(md, r"\n0:\d\d Claude\n")


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg not found")
class ExportTests(unittest.TestCase):
    def test_exports(self):
        ff = find_tool("ffmpeg")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = d / "output.mp4"
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=25:d=3",
                            "-f", "lavfi", "-i", "sine=d=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
            from editor.media import probe
            for kind in extras.EXPORTS:
                out = extras.export(d, src, kind, thumb_text="EDIT FASTER")
                self.assertTrue(out.exists() and out.stat().st_size > 0, kind)
            self.assertEqual((probe(d / "exports" / "square.mp4").width, probe(d / "exports" / "square.mp4").height),
                             (1080, 1080))


if __name__ == "__main__":
    unittest.main()
