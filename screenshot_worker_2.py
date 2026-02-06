#!/usr/bin/env python3
"""
Isolated Playwright screenshot worker.
Called as subprocess to avoid asyncio event loop conflicts.

Usage:
    python3 screenshot_worker.py <html_file> <output_path> <width> <height>
"""

import sys
import asyncio
from pathlib import Path


async def take_screenshot(html_path: str, output_path: str, width: int, height: int):
    """Take screenshot using async Playwright API."""
    from playwright.async_api import async_playwright

    # Read HTML content
    html = Path(html_path).read_text(encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.set_content(html)

        # Wait for fonts to load
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(0.3)

        # Screenshot
        await page.screenshot(path=output_path, type="jpeg", quality=95)
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: screenshot_worker.py <html_file> <output_path> <width> <height>")
        sys.exit(1)

    html_file = sys.argv[1]
    output_path = sys.argv[2]
    width = int(sys.argv[3])
    height = int(sys.argv[4])

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(take_screenshot(html_file, output_path, width, height))
    print("OK")
