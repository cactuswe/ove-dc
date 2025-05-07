# main.py  –  Discord‑bot som proxyar mot AI Horde 24/7 på Koyeb
import os, time, logging, requests, asyncio
import threading, http.server, socketserver
import discord
from discord.ext import commands

# --------------------------------------------------------------
# 0. Minimal HTTP‑server → Koyeb health‑check svarar 200 OK
# --------------------------------------------------------------
threading.Thread(
    target=lambda: socketserver.TCPServer(("0.0.0.0", 8080),
                                          http.server.SimpleHTTPRequestHandler).serve_forever(),
    daemon=True).start()

# --------------------------------------------------------------
# 1. Konfiguration
# --------------------------------------------------------------
HORDE_KEY = os.getenv("HORDE_KEY", "")           # valfritt
BASE_URL  = "https://aihorde.net/api/v2"
ASYNC_URL = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2. Funktion som anropar AI Horde och returnerar text
# --------------------------------------------------------------
def horde_infer(prompt: str) -> str:
    payload = {
        "prompt": prompt,
        "max_tokens": 120,
        # Kommentera bort "models" om du vill låta Horde välja ledig modell
        "models": ["Pygmalion-2-7b"],
        "params": {
            "temperature": 0.8,
            "top_p": 0.95,
            "max_context_length": 2048,
        },
    }
    headers = {"apikey": HORDE_KEY} if HORDE_KEY else {}

    try:
        resp = requests.post(ASYNC_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError:
        logging.error("POST %s → %s %s", ASYNC_URL, resp.status_code, resp.text.strip())
        return f"⚠️ Horde {resp.status_code}: {resp.json().get('message','')}"
    job_id = resp.json()["id"]

    while True:
        status = requests.get(STATUS_URL.format(id=job_id), timeout=30).json()
        if status["state"]["status"] == "done":
            return status["generations"][0]["text"].strip()
        time.sleep(1)

# --------------------------------------------------------------
# 3. Discord‑bot setup
# --------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True               # ← krävs för on_message
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info("✅  %s är online – guilds: %d", bot.user, len(bot.guilds))

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return

    # Test‑kommando
    if msg.content.lower().startswith("!ping"):
        await msg.channel.send("pong")
        return

    # Skicka texten till Horde utan att blockera event‑loopen
    loop = asyncio.get_running_loop()
    reply = await loop.run_in_executor(None, horde_infer, msg.content)
    await msg.channel.send(reply)

# --------------------------------------------------------------
# 4. Starta boten
# --------------------------------------------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN saknas i miljön")
bot.run(TOKEN)
