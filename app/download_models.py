"""Download the speech-to-text models named in config.yaml into ..\\models (run once, needs internet).

    python download_models.py            # every model in config.yaml
    python download_models.py <repo id>  # one specific CTranslate2 Whisper model from Hugging Face
"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.pop("HF_HUB_OFFLINE", None)

from huggingface_hub import snapshot_download  # noqa: E402

from editor.config import MODELS_DIR, load_config  # noqa: E402

FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
SIZES = {"small": "Systran/faster-whisper-small", "medium": "Systran/faster-whisper-medium",
         "large-v3": "Systran/faster-whisper-large-v3"}


def main() -> None:
    cfg = load_config()["whisper"]
    names = sys.argv[1:] or [cfg["model"], *(cfg.get("language_models") or {}).values()]
    for name in dict.fromkeys(names):
        repo = SIZES.get(name, name)
        print(f"\n== {repo} -> {MODELS_DIR}")
        t = time.time()
        path = snapshot_download(repo, cache_dir=str(MODELS_DIR), allow_patterns=FILES)
        size = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path)) / 1e9
        print(f"   done in {time.time() - t:.0f}s, {size:.2f} GB at {path}")
        try:
            with open(os.path.join(path, "config.json"), encoding="utf-8") as f:
                conf = json.load(f)
            heads = conf.get("alignment_heads")
            print("   word timestamps: " + ("alignment heads included (good)" if heads else
                  "no alignment heads in config; faster-whisper falls back to defaults, check timing on a test clip"))
        except OSError:
            pass
    print("\nAll models ready. Start the editor with run.bat.")


if __name__ == "__main__":
    main()
