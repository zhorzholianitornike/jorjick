#!/usr/bin/env python3
"""Downloads Noto Sans Georgian from Google Fonts.

Run once before the first card generation:
    python3 setup_fonts.py
"""

import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"

# Variable-weight font — works for both name (bold) and body (regular)
FONT_URL  = (
    "https://github.com/google/fonts/raw/main/"
    "ofl/notsansgeorgian/NotoSansGeorgian%5Bwght%5D.ttf"
)
FONT_FILE = FONTS_DIR / "NotoSansGeorgian.ttf"


def download():
    FONTS_DIR.mkdir(exist_ok=True)

    if FONT_FILE.exists():
        print(f"[OK] Font already present at {FONT_FILE}")
        return

    print(f"[>>] Downloading NotoSansGeorgian …")
    urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    print(f"[OK] Saved → {FONT_FILE}")


if __name__ == "__main__":
    download()
