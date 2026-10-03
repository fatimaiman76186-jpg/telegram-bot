"""Telegram bot: send a video (or a link) and get back vertical clips for Shorts/Reels."""
import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler, filters)

import clipper

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("clipbot")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Optional: comma-separated Telegram user IDs allowed to use the bot (empty = everyone)
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
# If you run a local Bot API server (see README), set this to lift the 20MB download / 50MB upload limits
LOCAL_API = os.getenv("TELEGRAM_LOCAL_API_URL")

URL_RE = re.compile(r"https?://\S+")
busy: set[int] = set()  # one job per user at a time


def allowed(update: Update) -> bool:
    return not ALLOWED or (update.effective_user and update.effective_user.id in ALLOWED)


async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "Send me a video file or a link (YouTube etc.) and I'll cut it into vertical "
        "9:16 clips with captions, ready for Shorts or Reels.\n\n"
        "Add the word 'nocaps' in the caption/message to skip captions."
    )


async def download_url(url: str, dest: Path) -> Path:
    def _dl():
        import yt_dlp
        opts = {"outtmpl": str(dest / "source.%(ext)s"), "format": "mp4/best[ext=mp4]/best",
                "quiet": True, "noplaylist": True, "merge_output_format": "mp4"}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return Path(ydl.prepare_filename(info))
    return await asyncio.to_thread(_dl)


async def process(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *, tg_file=None, url=None, captions=True):
    user_id = update.effective_user.id
    if user_id in busy:
        await update.message.reply_text("Still working on your previous video. Please wait.")
        return
    busy.add(user_id)
    workdir = Path(tempfile.mkdtemp(prefix="clipbot_"))
    status = await update.message.reply_text("Got it. Downloading...")
    loop = asyncio.get_running_loop()

    def progress(msg: str):
        asyncio.run_coroutine_threadsafe(status.edit_text(msg), loop)

    try:
        if url:
            video = await download_url(url, workdir)
        else:
            video = workdir / "source.mp4"
            f = await tg_file.get_file()
            await f.download_to_drive(video)

        clips = await asyncio.to_thread(clipper.make_clips, video, workdir / "out", captions, progress)
        await status.edit_text(f"Done. Sending {len(clips)} clip(s)...")
        for i, c in enumerate(clips, 1):
            caption = f"Clip {i}: {c.get('title', '')}\n{c.get('reason', '')}"[:1000]
            with open(c["path"], "rb") as fh:
                await update.message.reply_video(fh, caption=caption, supports_streaming=True,
                                                 read_timeout=300, write_timeout=300)
    except Exception as e:  # noqa: BLE001
        log.exception("processing failed")
        msg = str(e)
        if "File is too big" in msg:
            msg = ("Telegram won't let bots download files over 20MB. Send a link instead, "
                   "or run the bot with a local Bot API server (see README).")
        await update.message.reply_text(f"Something went wrong: {msg[:300]}")
    finally:
        busy.discard(user_id)
        shutil.rmtree(workdir, ignore_errors=True)


async def on_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    m = update.message
    tg_file = m.video or m.document
    captions = "nocaps" not in (m.caption or "").lower()
    await process(update, ctx, tg_file=tg_file, captions=captions)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    text = update.message.text or ""
    m = URL_RE.search(text)
    if not m:
        await update.message.reply_text("Send a video file or a link.")
        return
    await process(update, ctx, url=m.group(0), captions="nocaps" not in text.lower())


def main():
    builder = Application.builder().token(TOKEN).concurrent_updates(True)
    if LOCAL_API:
        builder = builder.base_url(f"{LOCAL_API}/bot").base_file_url(f"{LOCAL_API}/file/bot").local_mode(True)
    app = builder.build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, on_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot running")
    app.run_polling()


if __name__ == "__main__":
    main()
