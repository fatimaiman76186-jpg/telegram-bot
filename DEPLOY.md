# Deploying so you only use Telegram

Once deployed, the bot runs on a server 24/7 and restarts itself after crashes or reboots. You never touch the server again except to update it.

## Where to host

Transcription (Whisper) and video encoding need real CPU and RAM, so most free web-app hosts (512MB RAM) will crash. Realistic options:

| Option | Cost | Notes |
|---|---|---|
| **Oracle Cloud Always Free** (ARM, up to 4 cores / 24GB) | Free | Best specs for free, but signup can be fussy (card required, capacity varies by region). |
| **Cheap VPS** (Hetzner, DigitalOcean, Contabo) | roughly $4-6/month | Easiest and most reliable. Pick 2 vCPU / 4GB RAM. |
| **Your own PC or an old laptop** | Free | Fine if it stays on. Same Docker steps. |

On 2GB RAM use `WHISPER_MODEL=base` in `.env`; with 4GB, `small` is fine.

## Steps (any Ubuntu/Debian server)

```bash
# 1. Install Docker (once)
curl -fsSL https://get.docker.com | sh

# 2. Copy the project to the server (from your computer)
scp -r clipbot/ user@YOUR_SERVER_IP:~/clipbot

# 3. On the server
cd ~/clipbot
cp .env.example .env && nano .env      # set TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, ANTHROPIC_API_KEY (or leave empty)
docker compose up -d --build

# 4. Check it
docker compose logs -f bot             # look for "Bot running"
```

Then message your bot in Telegram. Stop with `docker compose down`.

**Updating** after code changes: copy the files again, then `docker compose up -d --build`.

## Large videos (optional)

Without this, send YouTube links or files under 20MB. For bigger files:

1. Get an `api_id` and `api_hash` at https://my.telegram.org (API development tools).
2. Add to `.env`:
   ```
   TELEGRAM_API_ID=...
   TELEGRAM_API_HASH=...
   TELEGRAM_LOCAL_API_URL=http://telegram-bot-api:8081
   ```
3. Log the bot out of Telegram's cloud API once (required before switching): open `https://api.telegram.org/bot<YOUR_TOKEN>/logOut` in a browser. Wait about 10 minutes before starting.
4. Start with the extra service: `docker compose --profile bigfiles up -d --build`

## Security

- Set `ALLOWED_USER_IDS` to your own Telegram ID, or strangers can use your server.
- Never commit or share `.env`; it holds your bot token.
- Only clip videos you have the rights to repost.
