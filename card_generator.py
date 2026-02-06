#!/usr/bin/env python3
"""
News-card generator — HTML/CSS template + Playwright screenshot.

New design features:
- Flexbox layout (content anchored to bottom)
- Dark gradient overlay (80% from bottom)
- Geometric shape overlay (diagonal triangle)
- Red square + name + SVG separator line
- Bottom red branding bar

Usage:
    from card_generator import CardGenerator
    gen = CardGenerator(logo_path="logo.png")   # logo optional
    gen.generate("photo.jpg", "Name", "Text …", "out.jpg")
    # or with URL:
    gen.generate_from_url("https://example.com/photo.jpg", "Name", "Text", "out.jpg")
"""

import os
import base64
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# CARD SIZE (pixels)
# ---------------------------------------------------------------------------
CARD_W = 1080
CARD_H = 1350

# ---------------------------------------------------------------------------
# Load font as base64 for embedding in HTML
# ---------------------------------------------------------------------------
def _get_font_base64() -> str:
    """Load Helvetica Georgian font as base64, fallback to Noto."""
    font_path = Path(__file__).parent / "fonts" / "HELVETICANEUELTGEO-55ROMAN.otf"
    if not font_path.exists():
        font_path = Path(__file__).parent / "fonts" / "NotoSansGeorgian.ttf"
    if font_path.exists():
        with open(font_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

# ---------------------------------------------------------------------------
# HTML TEMPLATE
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ka">
<head>
<meta charset="UTF-8">
<style>
  @font-face {{
    font-family: 'HelveticaGeo';
    src: url('data:font/otf;base64,{font_base64}') format('opentype');
    font-weight: normal;
    font-style: normal;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    margin: 0;
    padding: 0;
    width: {width}px;
    height: {height}px;
    overflow: hidden;
  }}

  .news-card {{
    position: relative;
    width: {width}px;
    height: {height}px;
    background-size: cover;
    background-position: center top;
    overflow: hidden;
    font-family: 'HelveticaGeo', 'Noto Sans Georgian', sans-serif;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
  }}

  .overlay-dark {{
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 80%;
    background: linear-gradient(to top, rgba(13, 18, 30, 1) 0%, rgba(13, 18, 30, 0.95) 45%, rgba(13, 18, 30, 0) 100%);
    z-index: 1;
  }}

  .geometric-shape {{
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 60%;
    background: linear-gradient(to right, rgba(255,255,255,0.06), transparent);
    z-index: 2;
    clip-path: polygon(0 0, 45% 25%, 0% 100%);
    pointer-events: none;
  }}

  .logo-container {{
    position: absolute;
    top: 60px;
    right: 60px;
    width: 120px;
    z-index: 10;
  }}
  .logo-container img {{ width: 100%; display: block; }}

  .content {{
    position: relative;
    z-index: 10;
    padding: 60px;
    padding-bottom: 0;
    color: #ffffff;
    display: flex;
    flex-direction: column;
  }}

  .header-box {{
    display: flex;
    align-items: center;
    margin-bottom: 0;
    padding-bottom: 0;
  }}

  .red-square {{
    width: 28px;
    height: 28px;
    background-color: #e60000;
    margin-right: 24px;
    flex-shrink: 0;
    margin-top: 5px;
  }}

  .name {{
    font-size: 62px;
    font-weight: 700;
    text-transform: uppercase;
    margin: 0;
    line-height: 1;
    color: #ffffff;
  }}

  .line-container {{
    width: 100%;
    height: 52px;
    margin-top: 0px;
    margin-bottom: 0px;
    display: flex;
    align-items: flex-end;
  }}

  .custom-line-svg {{
    width: 100%;
    height: 100%;
    display: block;
  }}

  .description {{
    font-size: 32px;
    line-height: 1.35;
    margin: 0;
    margin-top: 20px;
    color: #ffffff;
    text-transform: uppercase;
    opacity: 0.9;
  }}

  .bottom-branding-bar {{
    height: 28px;
    width: 100%;
    background-color: #e60000;
    z-index: 10;
    margin-top: 36px;
  }}
</style>
</head>
<body>

<div class="news-card" style="background-image: url('{image_data}');">

  {logo_html}

  <div class="overlay-dark"></div>
  <div class="geometric-shape"></div>

  <div class="content">

    <div class="header-box">
      <div class="red-square"></div>
      <h1 class="name">{name}</h1>
    </div>

    <div class="line-container">
      <svg class="custom-line-svg" viewBox="0 0 400 22" preserveAspectRatio="none">
        <polyline points="0,20 370,20 400,2"
                  fill="none"
                  stroke="#e60000"
                  stroke-width="2.5"
                  stroke-linejoin="round"
                  vector-effect="non-scaling-stroke" />
      </svg>
    </div>

    <p class="description">{text}</p>

  </div>

  <div class="bottom-branding-bar"></div>

</div>
</body>
</html>
"""


def _image_to_data_uri(path: str) -> str:
    """Convert local image file to base64 data URI."""
    ext = Path(path).suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


class CardGenerator:
    """Generate news cards using HTML/CSS template + Playwright screenshot."""

    def __init__(self, logo_path: Optional[str] = None):
        self.logo_path = logo_path
        self._browser = None
        self._playwright = None

    def _get_logo_html(self) -> str:
        """Return logo HTML block or empty string."""
        if self.logo_path and os.path.exists(self.logo_path):
            logo_uri = _image_to_data_uri(self.logo_path)
            return f'<div class="logo-container"><img src="{logo_uri}" alt="Logo"></div>'
        return ""

    def _build_html(
        self,
        image_data: str,
        name: str,
        text: str,
        width: int = CARD_W,
        height: int = CARD_H,
    ) -> str:
        """Build final HTML with all placeholders filled."""
        return HTML_TEMPLATE.format(
            width=width,
            height=height,
            image_data=image_data,
            name=_escape_html(name.upper()),
            text=_escape_html(text.upper()),
            logo_html=self._get_logo_html(),
            font_base64=_get_font_base64(),
        )

    def generate(
        self,
        photo_path: str,
        name: str,
        text: str,
        output_path: str = "card_output.jpg",
    ) -> str:
        """Generate card from local photo file → save as JPEG → return path."""
        image_data = _image_to_data_uri(photo_path)
        return self._render(image_data, name, text, output_path)

    def generate_from_url(
        self,
        image_url: str,
        name: str,
        text: str,
        output_path: str = "card_output.jpg",
    ) -> str:
        """Generate card from image URL → save as JPEG → return path."""
        return self._render(image_url, name, text, output_path)

    def _render(
        self,
        image_data: str,
        name: str,
        text: str,
        output_path: str,
    ) -> str:
        """Render HTML to image using subprocess worker (avoids asyncio conflicts)."""
        import subprocess
        import tempfile

        html = self._build_html(image_data, name, text)

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Write HTML to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(html)
            html_path = f.name

        try:
            # Get the path to screenshot_worker.py (same directory as this file)
            worker_path = Path(__file__).parent / "screenshot_worker.py"

            # Run screenshot worker as subprocess
            result = subprocess.run(
                ["python3", str(worker_path), html_path, output_path, str(CARD_W), str(CARD_H)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Screenshot failed: {result.stderr}")

        finally:
            # Clean up temp file
            Path(html_path).unlink(missing_ok=True)

        return output_path


# ---------------------------------------------------------------------------
# Sync wrapper for use in threads (web_app.py calls from asyncio.to_thread)
# ---------------------------------------------------------------------------
_generator_instance: Optional[CardGenerator] = None


def generate_card_sync(
    photo_path: str,
    name: str,
    text: str,
    output_path: str,
    logo_path: Optional[str] = None,
) -> str:
    """Thread-safe sync wrapper for card generation."""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = CardGenerator(logo_path=logo_path)
    return _generator_instance.generate(photo_path, name, text, output_path)


def generate_card_from_url_sync(
    image_url: str,
    name: str,
    text: str,
    output_path: str,
    logo_path: Optional[str] = None,
) -> str:
    """Thread-safe sync wrapper for card generation from URL."""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = CardGenerator(logo_path=logo_path)
    return _generator_instance.generate_from_url(image_url, name, text, output_path)


# ---------------------------------------------------------------------------
# Pillow-based Auto Card Generator (for auto-generate, no HTML template)
# ---------------------------------------------------------------------------
def generate_auto_card(
    photo_path: str,
    name: str,
    text: str,
    output_path: str,
) -> str:
    """
    Generate a simple news card using Pillow.
    Used for auto-generate flow (not the HTML template).

    Args:
        photo_path: Path to the photo file
        name: Headline/name (Georgian)
        text: Description text (Georgian)
        output_path: Where to save the card

    Returns:
        output_path
    """
    from PIL import Image, ImageDraw, ImageFont

    # Constants
    W, H = 1080, 1350
    ACCENT_RED = (229, 57, 53)
    WHITE = (255, 255, 255)

    # Load and resize photo to cover
    img = Image.open(photo_path).convert("RGBA")
    ratio = max(W / img.width, H / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - W) // 2
    top = (nh - H) // 2
    img = img.crop((left, top, left + W, top + H))

    # Dark gradient overlay (bottom 70%)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    gradient_start = int(H * 0.3)
    for y in range(gradient_start, H):
        alpha = int(220 * ((y - gradient_start) / (H - gradient_start)))
        draw_ov.rectangle([0, y, W, y + 1], fill=(13, 18, 30, alpha))
    img = Image.alpha_composite(img, overlay)

    # Load Georgian font - TTF is more reliable with Pillow than OTF
    fonts_dir = Path(__file__).parent / "fonts"
    font_path = None

    # Priority: 1) Noto Sans Georgian (TTF, most reliable)
    #           2) Helvetica Georgian (OTF)
    candidates = [
        fonts_dir / "NotoSansGeorgian.ttf",
        fonts_dir / "HELVETICANEUELTGEO-55ROMAN.otf",
    ]

    for candidate in candidates:
        if candidate.exists():
            font_path = candidate
            print(f"[Font] Found: {candidate.name}")
            break

    # If no font found, download Noto
    if font_path is None:
        print("[Font] No Georgian font found, downloading...")
        try:
            from setup_fonts import download
            download()
            noto = fonts_dir / "NotoSansGeorgian.ttf"
            if noto.exists():
                font_path = noto
                print(f"[Font] Downloaded: {noto.name}")
        except Exception as e:
            print(f"[Font] Download failed: {e}")

    # Load font
    if font_path and font_path.exists():
        print(f"[Font] Loading: {font_path}")
        name_font = ImageFont.truetype(str(font_path), 54)
        text_font = ImageFont.truetype(str(font_path), 28)
    else:
        print("[Font] WARNING: No Georgian font, using system default (Georgian text will fail)")
        name_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # Text wrapping helper
    def wrap_text(txt, font, max_width):
        words = txt.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            bbox = font.getbbox(test)
            if bbox[2] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # Layout
    pad_left = 60
    pad_right = 60
    pad_bottom = 80
    bar_height = 20
    max_text_width = W - pad_left - pad_right

    # Wrap text (UPPERCASE)
    name_upper = name.upper()
    text_upper = text.upper()
    text_lines = wrap_text(text_upper, text_font, max_text_width)

    # Calculate positions from bottom
    text_height = len(text_lines) * 42  # line height
    name_bbox = name_font.getbbox(name_upper)
    name_height = name_bbox[3] - name_bbox[1]

    total_content_height = name_height + 20 + text_height  # 20px gap
    content_top = H - pad_bottom - bar_height - total_content_height

    # Draw red square + name
    square_size = 20
    square_y = content_top + (name_height - square_size) // 2
    draw.rectangle(
        [pad_left, square_y, pad_left + square_size, square_y + square_size],
        fill=ACCENT_RED
    )

    # Name with shadow
    name_x = pad_left + square_size + 15
    draw.text((name_x + 2, content_top + 2), name_upper, fill=(0, 0, 0, 150), font=name_font)
    draw.text((name_x, content_top), name_upper, fill=WHITE, font=name_font)

    # Description text
    text_y = content_top + name_height + 20
    for line in text_lines:
        draw.text((pad_left + 2, text_y + 2), line, fill=(0, 0, 0, 100), font=text_font)
        draw.text((pad_left, text_y), line, fill=WHITE, font=text_font)
        text_y += 42

    # Bottom red bar
    draw.rectangle([0, H - bar_height, W, H], fill=ACCENT_RED)

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(output_path, "JPEG", quality=95)

    return output_path
