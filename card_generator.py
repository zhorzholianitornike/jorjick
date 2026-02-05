#!/usr/bin/env python3
"""
News-card generator — portrait 1080×1350.
Design: diagonal dark overlay, red square name prefix, gradient separator line.

Layout:

    ┌─────────────────────────────────────┐
    │                          [logo]     │  ← top-right (optional)
    │                                     │
    │          person photo               │  ← clear area (top-right)
    │   ░░░ diagonal dark overlay ░░░░░░  │  ← left side darkens earlier
    │                                     │
    │  ■ NAME NAME                        │  38 px bold, red square, uppercase
    │  ─────────►                         │  ← 2 px gradient line (red → transparent)
    │  description text …                 │  16 px, normal case
    │  … wraps here.                      │
    └█████████████████████████████████████┘  20 px red bottom bar

Usage:
    from card_generator import CardGenerator
    gen = CardGenerator(logo_path="logo.png")   # logo optional
    gen.generate("photo.jpg", "Name", "Text …", "out.jpg")
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
# COLOURS
# ---------------------------------------------------------------------------
ACCENT_RED  = (255, 59, 0)          # #ff3b00
WHITE       = (255, 255, 255)
SHADOW      = (0, 0, 0, 128)        # text-shadow approximation

# ---------------------------------------------------------------------------
# NAME ROW
# ---------------------------------------------------------------------------
NAME_SIZE   = 38                    # font-size: 38px
SQUARE_SIZE = 18                    # .square  width & height
SQUARE_GAP  = 15                    # .square  margin-right

# ---------------------------------------------------------------------------
# SEPARATOR LINE  (gradient red → transparent)
# ---------------------------------------------------------------------------
LINE_H      = 2                     # height: 2px
LINE_GAP_T  = 12                    # margin-top: 12px
LINE_GAP_B  = 20                    # margin-bottom: 20px

# ---------------------------------------------------------------------------
# DESCRIPTION
# ---------------------------------------------------------------------------
DESC_SIZE   = 16                    # font-size: 16px
DESC_LH     = int(DESC_SIZE * 1.6)  # line-height: 1.6  → 25 px

# ---------------------------------------------------------------------------
# LAYOUT
# ---------------------------------------------------------------------------
PAD_L       = 80                    # content padding-left
PAD_R       = 80                    # content padding-right
PAD_BOT     = 90                    # content padding-bottom

# ---------------------------------------------------------------------------
# BOTTOM BAR
# ---------------------------------------------------------------------------
BAR_H       = 20                    # height: 20px

# ---------------------------------------------------------------------------
# LOGO
# ---------------------------------------------------------------------------
LOGO_TOP    = 35                    # top: 35px
LOGO_RIGHT  = 45                    # right: 45px
LOGO_W      = 65                    # img width: 65px

# ---------------------------------------------------------------------------
# DIAGONAL OVERLAY  (column-band dark gradient)
# ---------------------------------------------------------------------------
DIAG_COLS      = 8                  # column bands (more = smoother diagonal)
DIAG_START_L   = 0.28               # gradient-start fraction from top, left edge
DIAG_START_R   = 0.52               # gradient-start fraction from top, right edge
DIAG_MAX_ALPHA = 200                # darkest alpha value at the bottom

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
        img = self._diagonal_overlay(img)
        img = self._content(img, name.upper(), text)   # name uppercase, text as-is
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

    # ── diagonal overlay ───────────────────────────────────────────────────
    @staticmethod
    def _diagonal_overlay(img: Image.Image) -> Image.Image:
        """
        Dark gradient with a diagonal edge — transparent at top-right,
        dark at bottom.  Column bands give a smooth diagonal transition.
        """
        w, h  = img.size
        ov    = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(ov)

        col_w = w // DIAG_COLS
        for cx in range(DIAG_COLS):
            frac    = cx / max(DIAG_COLS - 1, 1)            # 0 … 1  left → right
            y_start = int(h * (DIAG_START_L + frac * (DIAG_START_R - DIAG_START_L)))
            x1      = cx * col_w
            x2      = (cx + 1) * col_w if cx < DIAG_COLS - 1 else w

            for y in range(y_start, h):
                t     = (y - y_start) / max(h - y_start, 1)
                alpha = min(int(t * DIAG_MAX_ALPHA), DIAG_MAX_ALPHA)
                draw.rectangle([x1, y, x2, y + 1], fill=(0, 0, 0, alpha))

        return Image.alpha_composite(img, ov)

    # ── text helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _shadow(draw, pos, text, font, color=WHITE):
        """Draw text with a simple drop-shadow."""
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

    # ── content: name + separator line + description ───────────────────────
    def _content(self, img: Image.Image, name: str, text: str) -> Image.Image:
        """
        Draws name row, gradient separator line, and description text.
        Returns the image (new object after the separator alpha-composite).
        """
        w, h       = img.size
        draw       = ImageDraw.Draw(img)

        name_font  = _get_font(NAME_SIZE)
        desc_font  = _get_font(DESC_SIZE)

        # ── measure & wrap ──
        max_desc_w = w - PAD_L - PAD_R
        lines      = self._wrap(text, max_desc_w, desc_font)
        name_h     = name_font.getbbox(name)[3] - name_font.getbbox(name)[1]

        total_h    = (
            name_h
            + LINE_GAP_T + LINE_H + LINE_GAP_B
            + len(lines) * DESC_LH
        )

        # ── anchor to bottom ──
        y = h - PAD_BOT - BAR_H - total_h

        # ── NAME ROW: [■ square] [NAME] ──
        sq_y = y + (name_h - SQUARE_SIZE) // 2
        draw.rectangle(
            [PAD_L, sq_y, PAD_L + SQUARE_SIZE, sq_y + SQUARE_SIZE],
            fill=ACCENT_RED,
        )
        self._shadow(draw, (PAD_L + SQUARE_SIZE + SQUARE_GAP, y), name, name_font)
        y += name_h

        # ── SEPARATOR LINE  (red → transparent, left → right) ──
        y       += LINE_GAP_T
        line_w   = w - PAD_L - PAD_R
        r, g, b  = ACCENT_RED

        # build 1-row gradient strip directly in memory (fast)
        strip_data = bytearray(line_w * 4)          # RGBA
        for px in range(line_w):
            a   = int(255 * (1 - px / max(line_w - 1, 1)))
            off = px * 4
            strip_data[off]   = r
            strip_data[off+1] = g
            strip_data[off+2] = b
            strip_data[off+3] = a

        strip = Image.frombytes("RGBA", (line_w, 1), bytes(strip_data))
        if LINE_H > 1:
            strip = strip.resize((line_w, LINE_H), Image.NEAREST)

        line_ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        line_ov.paste(strip, (PAD_L, y))
        img    = Image.alpha_composite(img, line_ov)   # new image
        draw   = ImageDraw.Draw(img)                   # refresh draw context
        y += LINE_H + LINE_GAP_B

        # ── DESCRIPTION ──
        for line in lines:
            self._shadow(draw, (PAD_L, y), line, desc_font)
            y += DESC_LH

        return img

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
        img.paste(logo, (img.width - logo.width - LOGO_RIGHT, LOGO_TOP), logo)
