# Clip Bot

Telegram bot that turns a long video into vertical 9:16 clips with burned-in captions, ready for YouTube Shorts, Instagram Reels, or TikTok.

## How it works

1. You send a video file or a link (YouTube, etc.).
2. `faster-whisper` transcribes it with word-level timestamps.
3. Claude reads the transcript and picks the most hook-driven, self-contained moments (falls back to a keyword/density heuristic if no API key is set).
4. `ffmpeg` cuts each moment, center-crops to 9:16, scales to 1080x1920, and burns in 3-words-at-a-time captions.
5. The bot sends the clips back with a title and the reason each was picked.

Add `nocaps` to your message or caption to skip captions.

## Setup

```bash
# 1. System dependency
sudo apt install ffmpeg        # macOS: brew install ffmpeg | Windows: winget install ffmpeg

# 2. Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Config
cp .env.example .env           # fill in TELEGRAM_BOT_TOKEN (from @BotFather) and ANTHROPIC_API_KEY

# 4. Run
python bot.py
```

## File size limits (important)

The public Telegram Bot API lets bots download files up to **20MB** and upload up to **50MB**. For longer videos you have two options:

- **Send a link** instead of the file (works with no limits on download; clips are small enough to send back).
- **Run a local Bot API server** (https://github.com/tdlib/telegram-bot-api), which raises limits to 2GB. Then set `TELEGRAM_LOCAL_API_URL=http://localhost:8081` in `.env`. Note: you must `logOut` the bot from the cloud API once before switching.

## Tuning

- `WHISPER_MODEL`: `tiny`/`base` are fast, `small` is a good default, `medium`/`large-v3` are more accurate (use a GPU).
- Clips are center-cropped. For talking-head content that's fine; for wide shots with the subject off-center, add face tracking (e.g. MediaPipe) in `render_clip`.

## Notes

- Only use videos you own or have rights to repost.
- Processing time is roughly 0.3-1x the video length on CPU.
