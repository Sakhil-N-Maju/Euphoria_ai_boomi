# Style: no talking head (faceless motion graphics)
There is NO face and NO camera footage. The reel is a sequence of hand-built SCENES (modelled on real reference reels)
on a clean background, with the spoken words as captions. The "transcript" is the script (spoken by a voice-over, or
timed at reading speed when there is no voice).
- keep = [[0, last_index]] - never cut anything from a script.
- One scene every 2-4 s, back to back, covering most of the reel; short plain-caption moments (1-2 s) in between are fine.
- Use ONLY the scene types listed for the chosen look (below). Vary them: never the same type twice in a row.
- Every scene SHOWS the idea (a device, a figure, an object), it does not re-type the sentence. Text on a scene is
  short (1-5 words per item). Captions already carry the full sentence; words shown in a scene are dropped from the
  captions automatically, so put the KEY words in the scene.
- Items: each item has the index of the word where it should appear ("word"), so things land exactly as they're said.
- headline: the hook (l1 = the question or claim, l2 = 1-3 punch words). back: never.
- accent: 4-8 key words.

## Scene types (fields; anything not listed is optional)
phone      a tilted 3D phone. title (app name), items [{text, word}] rows (mode "list") or chat bubbles (mode "chat"),
           or value + text (+prefix/suffix) for a big animated number (mode "stats").
code       an editor window typing code line by line. title (file name, e.g. "agent.py"), label (top-right tag),
           items [{text: one short code line, word}], highlight (0-based line to highlight). Real-looking code only.
timeline   an editing timeline with a moving playhead; items = 2-4 clips [{text, word}], title.
graph      a self-drawing curve. label (chip), title (second chip), curve (linear / ease-out / ease-in / spring / rise /
           drop), x_label, y_label, optional value + text for a result chip, word = when it starts drawing.
glowword   full-screen glowing 3D word: text (1 word, max 10 letters), sub (short line), word.
figures    two glowing stick figures. text (headline, 2-4 words), left / right (their labels: who they are),
           left_pose / right_pose (stand, wave, point, cheer, sad, walk), prop between them (car, laptop, phone, box,
           doc, house, money, chart, desk, none), left_mark / right_mark (check, x, none) popping at "word".
tags       neon outlined boxes: label, items [{text (1-2 words), word, strike: true to cross one out}]; 2-6 items.
speech     a stick figure talking: who (left/right), pose, items = 1-3 speech bubbles [{text, word}].
icons      2-4 glowing line icons with labels: label, items [{text, word, icon}]. icon is one of: check x search bulb
           chart clock money user users chat lock star bolt doc folder globe heart shield target rocket cart mail phone
           link play code brain.
notepad    torn ruled notepad with handwriting: text (the note, max ~8 words), circle (one word of the note to circle in
           red), big (optional 1 word stamped below, e.g. "NO"), word = when the circle draws.
bigtype    full-screen huge condensed word with a red swipe underline and a dictionary-style line: text (1 word), sub
           (its short definition), word.
magnify    big word over a brick wall; a magnifier slides in and reveals a hidden phrase: text (1 word), reveal (2-4
           words), word = the reveal moment.
polaroids  2-4 pinned instant photos with handwritten labels: items [{text, word}].
window     an app window with a number badge: title (app name), kind prompt (text is typed into the box, label = the
           placeholder), checklist (items get ticked), folder (text = folder name, a cursor opens it) or chat (items =
           bubbles).
statement  a full-screen card: text (1-3 words), sub.
