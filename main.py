# main.py  –  Discord‑bot som svarar via AI Horde när "ove" nämns
import os, time, logging, requests, asyncio, re
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
HORDE_KEY      = os.getenv("HORDE_KEY", "")
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
TRIGGER_REGEX  = re.compile(r"\bove\b", re.I)    # matchar ordet "ove" oavsett versaler

BASE_URL   = "https://aihorde.net/api/v2"
ASYNC_URL  = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2.  AI Horde‑anrop
# --------------------------------------------------------------
def horde_infer(prompt: str, timeout_s: int = 60) -> str:
    payload = {
        "prompt": prompt.strip(),
        "max_tokens": 120,
        "models": ["Pygmalion-2-7b"],
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
        return f"⚠️ Horde‑fel: {getattr(e.response, 'text', str(e))[:120]}"

    job_id = resp.json().get("id")
    if not job_id:
        return "⚠️ Kunde inte skapa Horde‑jobb."

    start = time.time()
    while True:
        try:
            status = requests.get(STATUS_URL.format(id=job_id), timeout=30).json()
        except requests.RequestException as e:
            logging.warning("Status‑poll fel: %s", e)
            time.sleep(2)
            continue

        if status.get("state", {}).get("status") == "done":
            gens = status.get("generations", [])
            return gens[0]["text"].strip() if gens else "⚠️ Inget svar genererades."
        if status.get("state", {}).get("status") == "faulted":
            return f"⚠️ Horde avbröt jobbet: {status['state'].get('error','okänt fel')}"

        if time.time() - start > timeout_s:
            return "⚠️ Horde tog för lång tid (>60 s). Försök igen senare."
        time.sleep(1)

# --------------------------------------------------------------
# 3.  Discord‑bot
# --------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info("✅  %s online – guilds: %d", bot.user, len(bot.guilds))

# ---------- kommandon -----------------------------------------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    """!ping  →  pong"""
    await ctx.send("pong")

# ---------- on_message‑lyssnare --------------------------------
@bot.event
async def on_message(message: discord.Message):
    # Låt command‑systemet köra först
    await bot.process_commands(message)

    # Ignorera bots & DM:s (valfritt – ta bort checken om du vill svara i DM)
    if message.author.bot or isinstance(message.channel, discord.DMChannel):
        return

    # Kör AI‑Horde om "ove" nämns
    if TRIGGER_REGEX.search(message.content):
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, horde_infer, message.content)
        await message.channel.send(reply)

# --------------------------------------------------------------
# 4.  Starta boten
# --------------------------------------------------------------
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN saknas i miljön")
bot.run(DISCORD_TOKEN)
