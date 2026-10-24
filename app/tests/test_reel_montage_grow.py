"""Tests for the reel format, grades, the beat-synced montage and the Grow tools.
Run:  python -m unittest discover tests   (renders are skipped if ffmpeg isn't available)"""
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editor import grow, montage, style  # noqa: E402
from editor.captions import cta_times, write_ass  # noqa: E402
from editor.config import find_tool  # noqa: E402
from editor.render import grade_chain, out_size, reel_crop  # noqa: E402


def _have_ffmpeg() -> bool:
    try:
        subprocess.run([find_tool("ffmpeg"), "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class ReelTests(unittest.TestCase):
    def test_reel_size_and_crop(self):
        self.assertEqual(out_size(1920, 1080, False, reel=True), (1080, 1920))
        self.assertEqual(out_size(1920, 1080, True, reel=True), (540, 960))
        self.assertEqual(reel_crop(1920, 1080, 0.5), "crop=606:1080:657:0")
        self.assertEqual(reel_crop(1920, 1080, 0.0), "crop=606:1080:0:0")       # clamped to the frame
        self.assertIsNone(reel_crop(1080, 1920))
        self.assertTrue(reel_crop(1080, 1080).startswith("crop=606:1080:"))     # square -> centre 9:16 slice

    def test_grades(self):
        self.assertIsNone(grade_chain("none"))
        self.assertIn("colorbalance", grade_chain("cinematic"))
        self.assertIsNone(grade_chain("look01", None))                         # never faked without the LUT
        chain = grade_chain("look01", "look01.cube")
        self.assertIn("lut3d=file='look01.cube':interp=tetrahedral", chain)
        self.assertIn("in_range=tv:in_color_matrix=bt709", chain)

    def test_style_keys(self):
        out = style.clean_style({"format": "reel", "face_x": 3, "grade": "look01", "cta_keyword": "GUIDE"})
        self.assertEqual(out, {"format": "reel", "face_x": 1.0, "grade": "look01", "cta_keyword": "GUIDE"})

    def test_cta_types_in_last_seconds(self):
        start, typing, letters = cta_times(20.0, "GUIDE")
        self.assertAlmostEqual(start, 17.0)
        self.assertEqual(len(letters), 5)
        self.assertTrue(all(b > a for a, b in zip(letters, letters[1:])))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.ass"
            write_ass([], (1080, 1920), {"font": "Arial"}, p, style={**style.DEFAULTS, "format": "reel",
                                                                      "cta_keyword": "GUIDE"}, duration=20.0)
            text = p.read_text(encoding="utf-8-sig")
        self.assertIn("GUID|", text)
        self.assertIn("}GUIDE", text)


def synth_song(path: Path, bpm=120, seconds=36, intro=8.0, drop=20.0, sr=22050):
    t = np.arange(int(sr * seconds)) / sr
    y = np.zeros_like(t)
    beat = 60 / bpm
    rng = np.random.default_rng(1)
    for k in range(int(seconds / beat)):
        s, tb = int(k * beat * sr), k * beat
        n = int(0.04 * sr)
        h = s + int(beat * sr / 2)
        y[h:h + n] += rng.standard_normal(min(n, y.size - h)) * 0.06          # off-beat hats
        if tb >= intro:
            n = int(0.3 * sr)
            tt = np.arange(min(n, y.size - s)) / sr
            amp = 0.5 if tb < drop else 0.95
            accent = 1.0 if k % 4 == 0 else 0.6                                    # beat 1 of the bar is louder
            y[s:s + tt.size] += np.sin(2 * np.pi * (50 + 80 * np.exp(-tt / 0.03)) * tt) * np.exp(-tt / 0.15) * amp * accent
    pcm = (np.clip(y, -1, 1) * 30000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg not found")
class SongTests(unittest.TestCase):
    def test_beat_grid_start_and_drop(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "song.wav"
            synth_song(p)
            a = montage.analyze_song(p)
        self.assertAlmostEqual(a["bpm"], 120, delta=2)
        self.assertAlmostEqual(a["start"], 8.0, delta=0.08)      # skips the intro, lands on the kick, not the hat
        self.assertAlmostEqual(a["drop"], 20.0, delta=0.08)


class MontagePlanTests(unittest.TestCase):
    SONG = {"bpm": 120.0, "bar": 2.0, "bars": [2.0 * i for i in range(20)], "start": 8.0, "drop": 22.0,
            "duration": 40.0, "beats": []}

    def clips(self, n):
        return [{"name": f"c{i}", "duration": 4.0, "fps": 30, "motion": float(i == 2) * 10 + 1, "peak": 2.0,
                 "doubled": False} for i in range(n)]

    def test_hero_on_drop_no_repeats(self):
        p = montage.plan_montage(self.SONG, self.clips(7), 20)
        names = [s["name"] for s in p["segments"]]
        self.assertEqual(len(names), len(set(names)))
        hero = next(s for s in p["segments"] if s["hero"])
        self.assertEqual(hero["name"], "c2")
        self.assertAlmostEqual(hero["start"], p["drop"], delta=1.01)
        self.assertEqual(hero["transition_in"], "zoomin")
        for s in p["segments"][1:]:
            self.assertIn(s["transition_in"], ("fade", "hblur", "zoomin"))  # no slides, spins or flashes
        for s in p["segments"]:
            self.assertLessEqual(s["in"] + s["span"], 4.0 + 1e-6)          # never runs past the clip

    def test_speed_expr_is_monotonic(self):
        expr = montage.speed_expr(2.0, 1.0, 0.3)
        f = lambda T: eval(expr.replace("if(lt(", "_if(_lt(").replace("T", str(T)),  # noqa: E731
                           {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b})
        vals = [f(x / 50) for x in range(0, 66)]
        self.assertTrue(all(b >= a for a, b in zip(vals, vals[1:])))
        self.assertAlmostEqual(f(montage.source_span(2.0, 1.0, 0.3)), 2.0, delta=0.02)


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg not found")
class MontageRenderTests(unittest.TestCase):
    def test_render_small_montage(self):
        ff = find_tool("ffmpeg")
        with tempfile.TemporaryDirectory() as d:
            old = montage.MONTAGES_DIR
            montage.MONTAGES_DIR = Path(d) / "m"
            montage.MONTAGES_DIR.mkdir()
            try:
                m = montage.create("t")
                md = montage.mdir(m["id"])
                for k, src in enumerate(["testsrc2=s=320x240:r=30:d=3", "smptebars=s=320x240:r=30:d=3",
                                         "mandelbrot=s=320x240:r=30"]):
                    p = md / f"up{k}.mp4"
                    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src, "-t", "3",
                                    "-pix_fmt", "yuv420p", str(p)], check=True)
                    montage.add_clip(m["id"], p, f"clip{k}.mp4")
                synth_song(md / "upsong.wav", seconds=24, intro=2.0, drop=8.0)
                montage.set_song(m["id"], md / "upsong.wav", "song.wav")
                montage.make_plan(m["id"], 8, "cinematic")
                montage.update_meta(m["id"], draft=True)
                out = montage.render_montage(m["id"])
                from editor.media import probe
                info = probe(out)
                self.assertEqual((info.width, info.height), (540, 960))
                self.assertTrue(info.has_audio)
                self.assertTrue((md / "sheet_v1.jpg").exists())
            finally:
                montage.MONTAGES_DIR = old


class GrowTests(unittest.TestCase):
    def test_take_metrics(self):
        words = [{"i": i, "text": t, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, t in
                 enumerate("Stop editing by hand. Here is how.".split())]
        m = grow.take_metrics({"words": words, "segments": []}, {"filler_words": [1], "retakes": []})
        self.assertEqual(m["words"], 7)
        self.assertEqual(m["filler_words"], 1)
        self.assertIn("Stop editing", m["first_3_seconds"])

    def test_read_file_rejects_paths(self):
        with self.assertRaises(KeyError):
            grow.read_file("../config.yaml")

    def test_script_splits_style(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d, mock.patch.object(grow, "GROW_DIR", Path(d)), \
                mock.patch.object(grow, "chat_text", return_value="## Script\nhi\n=====STYLE.MD=====\nShort."):
            name, md, st = grow.script({"reference": "[0.0s] hello"})
            self.assertEqual(md, "## Script\nhi")
            self.assertEqual(st, "Short.")
            self.assertTrue((Path(d) / "style.md").exists())


if __name__ == "__main__":
    unittest.main()
