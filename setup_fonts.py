#!/usr/bin/env python3
"""Downloads Noto Sans Georgian from Google Fonts.

Run once before the first card generation:
    python3 setup_fonts.py
"""

import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"

# Variable-weight font (axes: wdth, wght)
FONT_URL  = (
    "https://raw.githubusercontent.com/google/fonts/main/"
    "ofl/notosansgeorgian/NotoSansGeorgian%5Bwdth%2Cwght%5D.ttf"
)
FONT_FILE = FONTS_DIR / "NotoSansGeorgian.ttf"


def download():
    FONTS_DIR.mkdir(exist_ok=True)

    if FONT_FILE.exists():
        print(f"[OK] Font already present at {FONT_FILE}")
        return

    print(f"[>>] Downloading NotoSansGeorgian …")
    try:
        urllib.request.urlretrieve(FONT_URL, FONT_FILE)
        print(f"[OK] Saved → {FONT_FILE}")
    except Exception as exc:
        print(f"[!] Font download failed: {exc}")
        print(f"[!] App will use fallback system font")


if __name__ == "__main__":
    download()
