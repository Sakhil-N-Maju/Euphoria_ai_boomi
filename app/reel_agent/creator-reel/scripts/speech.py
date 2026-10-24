"""Audio facts the cutter trusts more than Whisper's word timings (no AI, numpy only).

Whisper's word times are often off: zero-length words, an "umm" folded into the next word, words that run long
over a pause. So the cutter asks the audio itself:
  silences(a, b)   quiet stretches (a pause)                      -> tightened
  sustained(a, b)  one steady voiced sound for 0.22 s+ (umm, aaa,  -> cut, when it sits outside a word or
                   a drawn-out "sooo")                                 makes a word far longer than normal
  speech_runs()    where someone is talking                        -> finds talk that Whisper skipped
  edge_out/edge_in where a kept word really ends / starts           -> never clip the end of a word
All times are seconds on the source timeline (audio16k.wav = src.mp4)."""
import re
import numpy as np, soundfile as sf

HOP = 0.01

FILLERS = {'um', 'umm', 'ummm', 'uh', 'uhh', 'uhm', 'hmm', 'hm', 'mm', 'mmm', 'erm', 'er', 'ah', 'aah', 'aa', 'aaa',
           'eh', 'ehh', 'ahh', 'ഉം', 'ആ', 'ആആ', 'ഏ', 'ഹ്മ്', 'ഹം', 'अं', 'उम', 'हम्म', 'आ'}

_FILLER_RE = re.compile(r'^(u+m+|u+h+m*|h+m+|m{2,}|a{2,}h*|a+h+|e+h+|e+r+m*|ah|eh|uh|um|hm)$')


def norm(w):
    return ''.join(c for c in str(w).lower() if c.isalnum() or ord(c) > 0x900).strip()


def is_filler(w):
    n = norm(w)
    return bool(n) and (n in FILLERS or bool(_FILLER_RE.match(n)))


class Audio:
    def __init__(self, path='audio16k.wav'):
        a, sr = sf.read(path)
        if a.ndim > 1:
            a = a.mean(1)
        self.sr, self.a = sr, a
        hop, win = int(sr * HOP), int(sr * 0.025)
        n = max(1, (len(a) - win) // hop)
        idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
        fr = a[idx] * np.hanning(win)
        sp = np.abs(np.fft.rfft(fr, 512, axis=1)) ** 2
        self.db = 10 * np.log10(sp.sum(1) / 512 + 1e-12)
        f = np.fft.rfftfreq(512, 1 / sr)
        edges = np.geomspace(80, 4000, 25)
        B = np.stack([sp[:, (f >= edges[k]) & (f < edges[k + 1])].sum(1) for k in range(24)], 1)
        L = np.log(B + 1e-10)
        L -= L.mean(1, keepdims=True)
        d = np.zeros(n)
        d[5:] = np.sqrt(((L[5:] - L[:-5]) ** 2).mean(1))       # how fast the sound changes (50 ms apart)
        self.flux = np.convolve(d, np.ones(7) / 7, 'same')
        self.n = n
        self.floor = float(np.percentile(self.db, 10))
        loud = float(np.percentile(self.db, 70))
        # quiet = within a few dB of the room noise; a room with echo gets a margin of a third of the speech range
        self.quiet_thr = self.floor + max(5.0, min(9.0, (loud - self.floor) / 3))
        self.voiced = self.db > self.floor + max(10.0, (loud - self.floor) * 0.55)
        v = self.flux[self.voiced]
        self.steady_thr = float(np.percentile(v, 25)) if len(v) > 50 else 0.0
        self.dur = len(a) / sr

    def i(self, t):
        return int(min(self.n, max(0, round(t / HOP))))

    def _runs(self, mask, a, b, min_len):
        i0, i1 = self.i(a), self.i(b)
        out, s = [], None
        for k in range(i0, i1):
            if mask[k] and s is None:
                s = k
            if (not mask[k] or k == i1 - 1) and s is not None:
                e = k + (1 if mask[k] else 0)
                if (e - s) * HOP >= min_len:
                    out.append((round(s * HOP, 3), round(e * HOP, 3)))
                s = None
        return out

    def silences(self, a, b, min_len=0.25):
        return self._runs(self.db < self.quiet_thr, a, b, min_len)

    def sustained(self, a, b, min_len=0.22):
        if not self.steady_thr:
            return []
        return self._runs(self.voiced & (self.flux < self.steady_thr), a, b, min_len)

    def speech_runs(self, min_len=0.3, bridge=0.15):
        """talking stretches over the whole file (short dips bridged)"""
        talk = self.db > self.quiet_thr + 3
        runs = self._runs(talk, 0, self.dur, 0.05)
        merged = []
        for s, e in runs:
            if merged and s - merged[-1][1] <= bridge:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        return [(s, e) for s, e in merged if e - s >= min_len]

    def edge_out(self, t, limit):
        """from a word's end t, walk forward while it is still loud; stop at limit"""
        k, kl = self.i(t), self.i(limit)
        k0 = k
        while k < kl and self.db[k] >= self.quiet_thr:
            k += 1
        if k >= kl and kl > k0 + 5 and self.db[min(kl, self.n - 1)] >= self.quiet_thr:   # still talking: softest spot
            k = k0 + 5 + int(self.db[k0 + 5:kl].argmin())
        return round(min(limit, k * HOP), 3)

    def edge_in(self, t, limit):
        """from a word's start t, walk back while it is still loud; stop at limit (< t)"""
        k, kl = self.i(t), self.i(limit)
        k0 = k
        while k > kl and self.db[k - 1] >= self.quiet_thr:
            k -= 1
        if k <= kl and k0 > kl + 5 and self.db[max(0, kl)] >= self.quiet_thr:
            k = kl + int(self.db[kl:k0 - 5].argmin())
        return round(max(limit, k * HOP), 3)


def expected_len(word):
    """rough spoken length of a word in seconds (generous)"""
    n = len(norm(word)) or 1
    return 0.28 + 0.085 * n
