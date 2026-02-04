#!/usr/bin/env python3
"""
News-card generator — BBC / CNN / FOX-style lower-third graphics.

Layout (matches the Georgian-news reference):

    ┌─────────────────────────────────────┐
    │                                     │
    │          person photo               │
    │                                     │
    │  ░░░ dark gradient starts here ░░░  │
    │                                     │
    │  NAME IN LARGE WHITE TEXT           │
    │  ════  ← accent bar                 │
    │  Smaller description / quote text   │
    │  that can wrap to several lines.    │
    └─────────────────────────────────────┘

Usage:
    from card_generator import CardGenerator

    gen = CardGenerator()                       # no logo
    gen = CardGenerator(logo_path="logo.png")   # with logo

    output = gen.generate(
        photo_path="photo.jpg",
        name="ირაკლი კობახიძე",
        text=" października ტქ ადი ...",
        output_path="card.jpg",
    )
"""

import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# DESIGN TOKENS  ← change these to tweak the look
# ---------------------------------------------------------------------------
OVERLAY_RATIO     = 0.44          # bottom 44 % of the image gets the gradient
OVERLAY_MAX_ALPHA = 160           # darkest pixel at the very bottom  (0-255)

NAME_FONT_SIZE    = 54
TEXT_FONT_SIZE    = 22
TEXT_COLOR        = (255, 255, 255)   # white

PADDING_LEFT      = 58            # left margin
PADDING_BOTTOM    = 52            # distance from the bottom edge

NAME_TO_ACCENT    = 10            # gap  name  →  accent bar
ACCENT_TO_TEXT    = 14            # gap  accent bar  →  first text line
LINE_HEIGHT       = TEXT_FONT_SIZE + 6

ACCENT_COLOR      = (30, 148, 185)   # teal
ACCENT_H          = 4                # bar height
ACCENT_W          = 130              # bar width

MAX_SIDE          = 1080             # long side of the output image

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
_FONT_PATH = Path(__file__).parent / "fonts" / "NotoSansGeorgian.ttf"

# Fallback system fonts (macOS / Linux)
_SYSTEM_FALLBACKS = [
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Return a FreeTypeFont.  Downloads Georgian font on first run if missing."""
    # 1) preferred: Noto Sans Georgian (downloaded by setup_fonts.py)
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)

    # 2) try to auto-download
    try:
        from setup_fonts import download
        download()
        if _FONT_PATH.exists():
            return ImageFont.truetype(str(_FONT_PATH), size)
    except Exception:
        pass

    # 3) system fallbacks
    for p in _SYSTEM_FALLBACKS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)

    # 4) PIL default (no Georgian glyphs, but won't crash)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# CardGenerator
# ---------------------------------------------------------------------------
class CardGenerator:
    """Overlay a lower-third news graphic onto a photo."""

    def __init__(self, logo_path: Optional[str] = None):
        self.logo_path = logo_path

    # ── public ─────────────────────────────────────────────────────────────
    def generate(
        self,
        photo_path: str,
        name: str,
        text: str,
        output_path: str = "card_output.jpg",
    ) -> str:
        """
        Create a news card and write it to *output_path*.

        Args:
            photo_path:  source photo (JPEG / PNG)
            name:        person's name (large text)
            text:        description / quote (smaller text, auto-wraps)
            output_path: where to save the result

        Returns:
            output_path
        """
        img = self._open(photo_path)
        img = self._gradient(img)
        self._lower_third(img, name, text)
        if self.logo_path and os.path.exists(self.logo_path):
            self._logo(img)

        img.convert("RGB").save(output_path, "JPEG", quality=95)
        return output_path

    # ── private ────────────────────────────────────────────────────────────
    @staticmethod
    def _open(path: str) -> Image.Image:
        """Open image, resize so the long side ≤ MAX_SIDE, return RGBA."""
        img = Image.open(path).convert("RGBA")
        if max(img.size) > MAX_SIDE:
            ratio = MAX_SIDE / max(img.size)
            img = img.resize(
                (int(img.size[0] * ratio), int(img.size[1] * ratio)),
                Image.LANCZOS,
            )
        return img

    @staticmethod
    def _gradient(img: Image.Image) -> Image.Image:
        """Semi-transparent dark gradient over the bottom portion."""
        w, h     = img.size
        overlay  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw     = ImageDraw.Draw(overlay)
        start_y  = int(h * (1 - OVERLAY_RATIO))
        span     = h - start_y

        for y in range(start_y, h):
            alpha = int(OVERLAY_MAX_ALPHA * ((y - start_y) / span))
            draw.rectangle([0, y, w, y + 1], fill=(0, 0, 0, alpha))

        return Image.alpha_composite(img, overlay)

    # ── text layout ────────────────────────────────────────────────────────
    @staticmethod
    def _wrap(text: str, max_px: int, font: ImageFont.FreeTypeFont) -> list[str]:
        """Word-wrap *text* so each line fits within *max_px* pixels."""
        words  = text.split()
        lines  = []
        line   = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if font.getbbox(candidate)[2] <= max_px:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    def _lower_third(self, img: Image.Image, name: str, text: str):
        """Draw name + accent bar + description onto *img* in-place."""
        w, h  = img.size
        draw  = ImageDraw.Draw(img)

        name_font = _get_font(NAME_FONT_SIZE)
        text_font = _get_font(TEXT_FONT_SIZE)

        # ── measure ──
        max_text_w  = w - PADDING_LEFT * 2
        desc_lines  = self._wrap(text, max_text_w, text_font)

        name_bbox   = name_font.getbbox(name)
        name_h      = name_bbox[3] - name_bbox[1]

        desc_block_h = len(desc_lines) * LINE_HEIGHT
        total_h      = name_h + NAME_TO_ACCENT + ACCENT_H + ACCENT_TO_TEXT + desc_block_h

        # ── positions (anchored to bottom-left) ──
        y = h - PADDING_BOTTOM - total_h

        # name
        draw.text((PADDING_LEFT, y), name, fill=TEXT_COLOR, font=name_font)
        y += name_h + NAME_TO_ACCENT

        # accent bar
        draw.rectangle(
            [PADDING_LEFT, y, PADDING_LEFT + ACCENT_W, y + ACCENT_H],
            fill=ACCENT_COLOR,
        )
        y += ACCENT_H + ACCENT_TO_TEXT

        # description lines
        for line in desc_lines:
            draw.text((PADDING_LEFT, y), line, fill=TEXT_COLOR, font=text_font)
            y += LINE_HEIGHT

    def _logo(self, img: Image.Image):
        """Paste logo in the top-right corner."""
        logo = Image.open(self.logo_path).convert("RGBA")
        logo.thumbnail((100, 100), Image.LANCZOS)
        img.paste(logo, (img.width - logo.width - 25, 25), logo)
