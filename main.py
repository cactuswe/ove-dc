# main.py  –  Discord‑bot som proxyar mot AI Horde (robust version)
import os, time, logging, requests, asyncio
import threading, http.server, socketserver
import discord
from discord.ext import commands

# --------------------------------------------------------------
# 0.  Mini‑HTTP‑server för Koyebs health‑check
# --------------------------------------------------------------
threading.Thread(
    target=lambda: socketserver.TCPServer(("0.0.0.0", 8080),
                                          http.server.SimpleHTTPRequestHandler).serve_forever(),
    daemon=True).start()

# --------------------------------------------------------------
# 1.  Konfiguration
# --------------------------------------------------------------
HORDE_KEY  = os.getenv("HORDE_KEY", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

BASE_URL   = "https://aihorde.net/api/v2"
ASYNC_URL  = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2.  AI Horde‑anrop med fel‑hantering
# --------------------------------------------------------------
def horde_infer(prompt: str, timeout_s: int = 60) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "⚠️ Jag behöver lite text att svara på 🙂"

    payload = {
        "prompt": prompt,
        "max_tokens": 120,
        "models": ["Pygmalion-2-7b"],      # ta bort om du vill låta Horde välja
        "params": {
            "temperature": 0.8,
            "top_p": 0.95,
            "max_context_length": 2048
        },
    }
    headers = {"apikey": HORDE_KEY} if HORDE_KEY else {}

    try:
        resp = requests.post(ASYNC_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error("POST fel → %s | %s", getattr(e.response, "status_code", "?"), e)
        return f"⚠️ Ove‑fel: {getattr(e.response, 'text', str(e))[:120]}"

    job_id = resp.json().get("id")
    if not job_id:
        return "⚠️ Kunde inte skapa Ove‑jobb."

    start = time.time()
    while True:
        try:
            status = requests.get(STATUS_URL.format(id=job_id), timeout=30).json()
        except requests.RequestException as e:
            logging.warning("Status‑poll fel: %s", e)
            time.sleep(2)
            continue

        state = status.get("state", {})
        if state.get("status") == "done":
            gens = status.get("generations", [])
            return gens[0]["text"].strip() if gens else "⚠️ Inget svar genererades."
        if state.get("status") == "faulted":
            return f"⚠️ Ove avbröt jobbet: {state.get('error','okänt fel')}"

        if time.time() - start > timeout_s:
            return "⚠️ Ove tog för lång tid (>60 s). Försök igen senare."
        time.sleep(1)

# --------------------------------------------------------------
# 3.  Discord‑bot
# --------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True   # måste även slås på i Dev Portal
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info("✅  %s online – guilds: %d", bot.user, len(bot.guilds))

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return

    # enkelt ping‑test
    if msg.content.lower().startswith("!ping"):
        await msg.channel.send("pong")
        return

    loop = asyncio.get_running_loop()
    reply = await loop.run_in_executor(None, horde_infer, msg.content)
    await msg.channel.send(reply)

# --------------------------------------------------------------
# 4.  Starta boten
# --------------------------------------------------------------
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN saknas i miljön")
bot.run(DISCORD_TOKEN)
