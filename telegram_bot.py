#!/usr/bin/env python3
"""
Telegram bot — news-card factory.

Flow:
    user  →  /start
    bot   →  "Send a photo"
    user  →  [photo]
    bot   →  "Now send name + text"
    user  →  ირაკლი კობახიძე
             "ტექსტი ...")
    bot   →  [generated card image]

Env vars:
    TELEGRAM_BOT_TOKEN   — Telegram bot token  (required)

Run:
    export TELEGRAM_BOT_TOKEN="123:ABC-..."
    python3 telegram_bot.py
"""

import os
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from card_generator import CardGenerator

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN")
TEMP     = Path("temp")
TEMP.mkdir(exist_ok=True)

# Set logo_path="logo.png" if you have a logo file
generator = CardGenerator(logo_path=None)

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------
PHOTO = 0   # waiting for photo
TEXT  = 1   # waiting for name + text


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context) -> int:
    """Entry point — tells the user what to do."""
    await update.message.reply_text(
        "News Card Bot\n\n"
        "1. Send a photo\n"
        "2. Then send name and text:\n\n"
        "    ირაკლი კობახიძე\n"
        '    "ტექსტი revet"\n\n'
        "/cancel — stop"
    )
    return PHOTO


async def receive_photo(update: Update, context) -> int:
    """Saves the photo, asks for text."""
    photo_file = await update.message.photo[-1].get_file()       # largest size
    path       = TEMP / f"{update.effective_user.id}_photo.jpg"
    photo_bytes = await photo_file.download_as_bytearray()
    path.write_bytes(photo_bytes)

    context.user_data["photo"] = str(path)
    await update.message.reply_text(
        "Photo saved.\n\n"
        "Now send:\n"
        "Name\n"
        '"text"'
    )
    return TEXT


async def receive_text(update: Update, context) -> int:
    """Parses name + text, generates the card, sends it back."""
    raw   = update.message.text.strip()
    parts = raw.split("\n", 1)                  # split on first newline only

    if len(parts) < 2:
        await update.message.reply_text('Send two lines:\n\nName\n"text"')
        return TEXT

    name = parts[0].strip()
    desc = parts[1].strip().strip('"')          # remove surrounding quotes

    photo_path = context.user_data.get("photo")
    if not photo_path:
        await update.message.reply_text("Photo lost. Press /start again.")
        return ConversationHandler.END

    out_path = TEMP / f"{update.effective_user.id}_card.jpg"

    try:
        generator.generate(photo_path, name, desc, str(out_path))

        with open(out_path, "rb") as f:
            await update.message.reply_photo(photo=f)
    except Exception as exc:
        await update.message.reply_text(f"Error generating card:\n{exc}")

    # cleanup temp files
    for p in (photo_path, str(out_path)):
        if os.path.exists(p):
            os.remove(p)
    context.user_data.clear()

    await update.message.reply_text("Done! /start for another card.")
    return ConversationHandler.END


async def cancel(update: Update, context) -> int:
    """Cancels the current flow."""
    context.user_data.clear()
    await update.message.reply_text("Cancelled. /start to begin again.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set.")

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PHOTO: [MessageHandler(filters.PHOTO,                      receive_photo)],
            TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND,     receive_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    print("[>>] Bot is running …  press Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
