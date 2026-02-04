#!/usr/bin/env python3
"""
News-card generator — portrait 1080×1350.
Design translated directly from the HTML/CSS reference template.

Layout:

    ┌─────────────────────────────────────┐
    │                          [logo]     │
    │                                     │
    │          person photo               │
    │                                     │
    │  ░░░ gradient (60 % … 0 %) ░░░░░░░  │
    │                                     │
    │  ● Name                             │  54 px bold, red dot prefix
    │  „                                  │  96 px opening mark
    │    Quote text …                     │  30 px, indented 42 px
    │    … wraps here.                    │
    │                            "        │  96 px closing mark, right
    └█████████████████████████████████████┘  18 px red bottom bar

Usage:
    from card_generator import CardGenerator
    gen = CardGenerator(logo_path="logo.png")   # logo optional
    gen.generate("photo.jpg", "Name", "Quote text …", "out.jpg")
"""

import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# CARD SIZE
# ---------------------------------------------------------------------------
CARD_W  = 1080
CARD_H  = 1350

# ---------------------------------------------------------------------------
# COLOURS  (match the CSS variables)
# ---------------------------------------------------------------------------
ACCENT_RED  = (229, 57, 53)          # --accent-red  #E53935
WHITE       = (255, 255, 255)
MARK_WHITE  = (255, 255, 255, 217)   # rgba(255,255,255,0.85)  for „ "
SHADOW      = (0, 0, 0, 128)        # text-shadow approximation

BLUE_OVERLAY = (20, 50, 110, 100)    # semi-transparent blue
BLUE_COVER_H = 0.70                  # covers top 70 % of the card

# ---------------------------------------------------------------------------
# NAME ROW
# ---------------------------------------------------------------------------
NAME_SIZE   = 54                     # font-size: 54px
DOT_W       = 10                     # .name::before  width/height
DOT_GAP     = 16                     # margin-right on the dot

# ---------------------------------------------------------------------------
# QUOTE BLOCK
# ---------------------------------------------------------------------------
QUOTE_SIZE  = 30                     # font-size: 30px
QUOTE_LH    = int(QUOTE_SIZE * 1.5)  # line-height: 1.5
QUOTE_INDENT= 42                     # padding-left: 42px
MARK_SIZE   = 96                     # font-size of „ and "
MARK_TOP    = -12                    # top: -12px on opening mark
MARK_GAP    = 16                     # margin-top on closing mark
QUOTE_BLOCK_MAX = 900                # max-width: 900px

# ---------------------------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------------------------
PAD_L       = 80                     # content padding-left
PAD_R       = 80                     # content padding-right
PAD_BOT     = 90                     # content padding-bottom
NAME_GAP    = 24                     # .name margin-bottom

# ---------------------------------------------------------------------------
# BOTTOM BAR
# ---------------------------------------------------------------------------
BAR_H       = 18                     # .bottom-accent height

# ---------------------------------------------------------------------------
# LOGO
# ---------------------------------------------------------------------------
LOGO_PAD    = 40                     # .logo padding
LOGO_W      = 90                     # .logo img width

# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
_FONT_PATH        = Path(__file__).parent / "fonts" / "NotoSansGeorgian.ttf"
_SYSTEM_FALLBACKS = [
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Load font — auto-downloads Georgian font on first use if missing."""
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)
    try:
        from setup_fonts import download
        download()
        if _FONT_PATH.exists():
            return ImageFont.truetype(str(_FONT_PATH), size)
    except Exception:
        pass
    for p in _SYSTEM_FALLBACKS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# CardGenerator
# ---------------------------------------------------------------------------
class CardGenerator:
    """Generate a 1080×1350 portrait news card."""

    def __init__(self, logo_path: Optional[str] = None):
        self.logo_path = logo_path

    # ── public ─────────────────────────────────────────────────────────────
    def generate(
        self,
        photo_path:  str,
        name:        str,
        text:        str,
        output_path: str = "card_output.jpg",
    ) -> str:
        """Generate card → save as JPEG → return output_path."""
        img = self._cover(photo_path)
        img = self._gradient(img)
        img = self._blue_overlay(img)
        self._content(img, name.upper(), text.upper())
        self._bottom_bar(img)
        if self.logo_path and os.path.exists(self.logo_path):
            self._logo(img)
        img.convert("RGB").save(output_path, "JPEG", quality=95)
        return output_path

    # ── photo: background-size: cover ──────────────────────────────────────
    @staticmethod
    def _cover(path: str) -> Image.Image:
        """Resize + centre-crop to CARD_W × CARD_H."""
        img   = Image.open(path).convert("RGBA")
        ratio = max(CARD_W / img.width, CARD_H / img.height)
        nw, nh = int(img.width * ratio), int(img.height * ratio)
        img   = img.resize((nw, nh), Image.LANCZOS)
        left  = (nw - CARD_W) // 2
        top   = (nh - CARD_H) // 2
        return img.crop((left, top, left + CARD_W, top + CARD_H))

    # ── gradient ───────────────────────────────────────────────────────────
    @staticmethod
    def _gradient(img: Image.Image) -> Image.Image:
        """
        Matches the CSS exactly:
            linear-gradient(to top,
                rgba(0,0,0,0.85)  0 %,   → bottom
                rgba(0,0,0,0.55) 25 %,
                rgba(0,0,0,0.0 ) 60 %)   → transparent
        """
        w, h  = img.size
        ov    = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(ov)

        y60   = h - int(h * 0.60)       # y where gradient becomes 0
        y25   = h - int(h * 0.25)       # y at the 0.55 keyframe

        for y in range(y60, h):
            if y < y25:                  # 60 %…25 %  →  alpha 0…140
                t     = (y - y60) / max(y25 - y60, 1)
                alpha = int(140 * t)
            else:                        # 25 %…0 %   →  alpha 140…217
                t     = (y - y25) / max(h - y25, 1)
                alpha = int(140 + 77 * t)
            draw.rectangle([0, y, w, y + 1], fill=(0, 0, 0, alpha))

        return Image.alpha_composite(img, ov)

    # ── blue overlay (top 70 %) ────────────────────────────────────────────
    @staticmethod
    def _blue_overlay(img: Image.Image) -> Image.Image:
        """Semi-transparent blue rectangle over the top 70 % of the card."""
        w, h  = img.size
        ov    = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(ov)
        draw.rectangle([0, 0, w, int(h * BLUE_COVER_H)], fill=BLUE_OVERLAY)
        return Image.alpha_composite(img, ov)

    # ── text helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _shadow(draw, pos, text, font, color=WHITE):
        """Draw text with a simple drop-shadow (approx text-shadow: 0 2px 4px)."""
        draw.text((pos[0] + 1, pos[1] + 2), text, fill=SHADOW, font=font)
        draw.text(pos,                       text, fill=color,  font=font)

    @staticmethod
    def _wrap(text: str, max_px: int, font: ImageFont.FreeTypeFont) -> list[str]:
        """Word-wrap so every line fits within max_px."""
        words, lines, cur = text.split(), [], ""
        for w in words:
            candidate = f"{cur} {w}".strip()
            if font.getbbox(candidate)[2] <= max_px:
                cur = candidate
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    # ── content: name row + quote block ────────────────────────────────────
    def _content(self, img: Image.Image, name: str, text: str):
        w, h      = img.size
        draw      = ImageDraw.Draw(img)

        name_font  = _get_font(NAME_SIZE)
        quote_font = _get_font(QUOTE_SIZE)
        mark_font  = _get_font(MARK_SIZE)

        # ── wrap quote lines ──
        max_q_w   = min(QUOTE_BLOCK_MAX, w - PAD_L - PAD_R) - QUOTE_INDENT
        lines     = self._wrap(text, max_q_w, quote_font)

        # ── measure heights ──
        name_h    = name_font.getbbox(name)[3] - name_font.getbbox(name)[1]
        close_bb  = mark_font.getbbox("\u201C")
        close_h   = close_bb[3] - close_bb[1]
        close_w   = close_bb[2] - close_bb[0]

        total_h   = (
            name_h
            + NAME_GAP
            + len(lines) * QUOTE_LH
            + MARK_GAP
            + close_h
        )

        # ── anchor to bottom ──
        y = h - PAD_BOT - BAR_H - total_h

        # ── NAME: [red dot] [name text] ──
        dot_y = y + (name_h - DOT_W) // 2
        draw.rectangle(
            [PAD_L, dot_y, PAD_L + DOT_W, dot_y + DOT_W],
            fill=ACCENT_RED,
        )
        self._shadow(draw, (PAD_L + DOT_W + DOT_GAP, y), name, name_font)
        y += name_h + NAME_GAP

        # ── QUOTE ──
        block_x = PAD_L                     # left edge of quote block
        text_x  = block_x + QUOTE_INDENT   # indented text start

        # opening „  — top: -12 px relative to the quote block
        self._shadow(draw, (block_x, y + MARK_TOP), "\u201E", mark_font, color=MARK_WHITE)

        # wrapped quote lines
        for line in lines:
            self._shadow(draw, (text_x, y), line, quote_font)
            y += QUOTE_LH

        # closing "  — right-aligned within QUOTE_BLOCK_MAX, margin-top 16
        y += MARK_GAP
        right_edge = min(block_x + QUOTE_BLOCK_MAX, w - PAD_R)
        self._shadow(draw, (right_edge - close_w, y), "\u201C", mark_font, color=MARK_WHITE)

    # ── full-width red bottom bar ──────────────────────────────────────────
    @staticmethod
    def _bottom_bar(img: Image.Image):
        draw = ImageDraw.Draw(img)
        w, h = img.size
        draw.rectangle([0, h - BAR_H, w, h], fill=ACCENT_RED)

    # ── logo (top-right) ───────────────────────────────────────────────────
    def _logo(self, img: Image.Image):
        logo = Image.open(self.logo_path).convert("RGBA")
        logo.thumbnail((LOGO_W, LOGO_W * 2), Image.LANCZOS)
        img.paste(logo, (img.width - logo.width - LOGO_PAD, LOGO_PAD), logo)
