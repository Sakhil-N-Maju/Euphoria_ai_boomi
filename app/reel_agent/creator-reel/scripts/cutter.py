"""Word ranges -> source time ranges to keep, using the audio itself for pauses, fillers and word edges.

plan_cuts(W, ranges, audio, pace) -> (keep [[t0, t1], ...], report dict)
  W       words.json list ({"w", "s", "e"})
  ranges  [[first_word, last_word], ...] to keep (from the plan)
  pace    "tight" (default): pauses over 0.25 s shrink to 0.12 s
          "natural": pauses over 0.45 s shrink to 0.25 s
Fillers go three ways: filler words Whisper wrote (um, uh, aa, ഉം ...), steady "uhhh / aaaa" sounds between words,
and steady sounds that make a word far longer than it should be (an "umm" Whisper glued onto "I")."""
from speech import expected_len, is_filler

PACES = {'tight': (0.25, 0.12), 'natural': (0.45, 0.25), 'loose': (0.8, 0.4)}


def _subtract(span, cuts):
    a, b = span
    out = []
    for c0, c1 in sorted(cuts):
        if c1 <= a or c0 >= b:
            continue
        if c0 > a:
            out.append([a, c0])
        a = max(a, c1)
    if a < b:
        out.append([a, b])
    return out


def plan_cuts(W, ranges, A, pace='tight', cut_fillers=True, protect=()):
    N = len(W)
    min_pause, keep_pause = PACES.get(pace, PACES['tight'])
    end = lambda i: max(W[i].get('e', W[i]['s'] + 0.3), W[i]['s'] + 0.04)
    rep = {'fillers': [], 'sounds': 0, 'pauses': 0, 'pause_s': 0.0}

    # 1. filler words split the ranges
    rngs = []
    for a, b in ranges:
        cur = None
        for i in range(a, b + 1):
            if cut_fillers and i not in protect and is_filler(W[i]['w']):
                rep['fillers'].append(i)
                if cur:
                    rngs.append(cur); cur = None
                continue
            cur = [cur[0], i] if cur else [i, i]
        if cur:
            rngs.append(cur)
    kept = set(i for a, b in rngs for i in range(a, b + 1))

    pieces = []
    for a, b in rngs:
        s, e = W[a]['s'], end(b)
        if e - s < 0.05:
            continue
        # 2. real word edges: walk to where the sound starts / stops (bounded by the neighbours)
        lim_in = max(end(a - 1) if a > 0 else 0.0, s - 0.4)
        short_by = max(0.0, expected_len(W[b]['w']) - (e - s if a == b else end(b) - W[b]['s']))
        lim_out = min(W[b + 1]['s'] if b + 1 < N else A.dur, e + 0.45 + short_by)
        s2 = max(lim_in, A.edge_in(s, lim_in) - 0.05)
        e2 = min(lim_out, A.edge_out(e, lim_out) + 0.08, A.dur)
        cuts = []
        # 3. long pauses inside the range
        for q0, q1 in A.silences(s2, e2, min_pause):
            if q0 <= s2 + 0.02 or q1 >= e2 - 0.02:
                continue
            c0, c1 = q0 + keep_pause * 0.45, q1 - keep_pause * 0.55
            if c1 - c0 > 0.05:
                cuts.append([c0, c1]); rep['pauses'] += 1; rep['pause_s'] += c1 - c0
        # 4. steady filler sounds (umm / aaa) that no kept word explains
        if cut_fillers:
            for r0, r1 in A.sustained(s2, e2):
                # a filler sits next to a pause; a long vowel inside a sentence doesn't
                if not (A.silences(r0 - 0.25, r0 + 0.01, 0.06) or A.silences(r1 - 0.01, r1 + 0.25, 0.06)):
                    continue
                mid = (r0 + r1) / 2
                host = [i for i in range(a, b + 1) if W[i]['s'] - 0.03 <= mid <= end(i) + 0.03]
                if host:                                   # inside a word whose timing looks sane: it's that word
                    i = host[0]
                    if end(i) - W[i]['s'] <= expected_len(W[i]['w']) + 0.15:
                        continue
                cuts.append([r0 - 0.02, r1 + 0.02]); rep['sounds'] += 1
        for p in _subtract([s2, e2], cuts):
            if p[1] - p[0] >= 0.1:
                pieces.append(p)

    pieces.sort()
    merged = []
    for a, b in pieces:
        if merged and a <= merged[-1][1] + 0.04:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    rep['pause_s'] = round(rep['pause_s'], 2)
    return [[round(a, 3), round(b, 3)] for a, b in merged], rep, kept


def plan_cuts_audio(W, A, pace='tight', cut_fillers=True, protect=(), cut_words=()):
    """"Keep everything I said" mode: the whole take stays; only the audio decides what goes.
    Removes: silence before the first and after the last sound, pauses longer than the pace allows, steady
    umm / aaa sounds next to a pause, filler words Whisper wrote (um, uh), and words the creator cut by hand.
    Speech Whisper missed (unclear words, mumbling) stays in, because nothing here depends on the transcript."""
    N = len(W)
    min_pause, keep_pause = PACES.get(pace, PACES['tight'])
    end = lambda i: max(W[i].get('e', W[i]['s'] + 0.3), W[i]['s'] + 0.04)
    rep = {'fillers': [], 'sounds': 0, 'pauses': 0, 'pause_s': 0.0}
    runs = A.speech_runs(min_len=0.08)
    if not runs:
        return [[0.0, round(A.dur, 3)]], rep, set(range(N))
    t0 = max(0.0, runs[0][0] - 0.12)
    t1 = min(A.dur, runs[-1][1] + 0.18)
    if W:
        t0 = min(t0, max(0.0, W[0]['s'] - 0.05))
        t1 = max(t1, min(A.dur, end(N - 1) + 0.1))
    cuts = []
    for q0, q1 in A.silences(t0, t1, min_pause):            # long pauses -> short pauses
        if q0 <= t0 + 0.02 or q1 >= t1 - 0.02:
            continue
        c0, c1 = q0 + keep_pause * 0.45, q1 - keep_pause * 0.55
        if c1 - c0 > 0.05:
            cuts.append([c0, c1]); rep['pauses'] += 1; rep['pause_s'] += c1 - c0
    if cut_fillers:
        for i in range(N):                                    # filler words with believable timing
            if i not in protect and is_filler(W[i]['w']) and end(i) - W[i]['s'] < 1.2:
                cuts.append([W[i]['s'] - 0.02, end(i) + 0.02]); rep['fillers'].append(i)
        for r0, r1 in A.sustained(t0, t1):                    # umm / aaa sounds that sit next to a pause
            if not (A.silences(r0 - 0.25, r0 + 0.01, 0.06) or A.silences(r1 - 0.01, r1 + 0.25, 0.06)):
                continue
            mid = (r0 + r1) / 2
            host = [i for i in range(N) if W[i]['s'] - 0.03 <= mid <= end(i) + 0.03]
            if host and end(host[0]) - W[host[0]]['s'] <= expected_len(W[host[0]]['w']) + 0.15:
                continue                                      # it's a real (long) word, not a filler
            cuts.append([r0 - 0.02, r1 + 0.02]); rep['sounds'] += 1
    hand = sorted(set(int(i) for i in cut_words if 0 <= int(i) < N))
    k = 0
    while k < len(hand):                                      # words cut by hand, contiguous runs together
        a = b = hand[k]
        while k + 1 < len(hand) and hand[k + 1] == b + 1:
            k += 1; b = hand[k]
        lo = end(a - 1) if a > 0 else 0.0
        hi = W[b + 1]['s'] if b + 1 < N else A.dur
        cuts.append([max(lo, W[a]['s'] - 0.04), min(hi, end(b) + 0.04)])
        k += 1
    pieces = [p for p in _subtract([t0, t1], cuts) if p[1] - p[0] >= 0.18]   # no blips between two cuts
    merged = []
    for a, b in pieces:
        if merged and a <= merged[-1][1] + 0.04:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    rep['pause_s'] = round(rep['pause_s'], 2)
    kept = set(range(N)) - set(rep['fillers']) - set(hand)
    return [[round(a, 3), round(b, 3)] for a, b in merged], rep, kept
