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
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
HORDE_KEY      = os.getenv("HORDE_KEY", "")
TRIGGER_REGEX  = re.compile(r"\bove\b", re.I)    # matchar ordet "ove"

BASE_URL   = "https://aihorde.net/api/v2"
ASYNC_URL  = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2.  AI Horde‑anrop med kö‑info och fail‑safe
# --------------------------------------------------------------
def horde_infer(prompt: str, timeout_s: int = 90) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "⚠️ Jag behöver lite text att svara på 🙂"

    payload = {
        "prompt": prompt,
        "max_tokens": 120,
        # Inga "models" → Horde väljer första lediga modell
        "params": {
            "temperature": 0.8,
            "top_p": 0.95,
            "max_context_length": 2048,
        },
    }
    headers = {"apikey": HORDE_KEY} if HORDE_KEY else {}

    try:
        r = requests.post(ASYNC_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        code = getattr(e.response, "status_code", "?")
        text = getattr(e.response, "text", str(e))[:120]
        logging.error("POST fel → %s | %s", code, text)
        return f"⚠️ Horde‑fel {code}: {text}"

    job = r.json()
    job_id = job.get("id")
    eta    = job.get("eta", "?")   # sekunder; kan saknas
    queue  = job.get("queued", 0)

    if eta != "?" and eta > timeout_s:
        return f"⏳ Horde‑kön är lång just nu ({eta//60} min). Försök igen lite senare!"

    start = time.time()
    while True:
        status = requests.get(STATUS_URL.format(id=job_id), timeout=30).json()

        if status.get("state", {}).get("status") == "done":
            gens = status.get("generations", [])
            return gens[0]["text"].strip() if gens else "⚠️ Inget svar genererades."

        if status.get("state", {}).get("status") == "faulted":
            return f"⚠️ Horde avbröt jobbet: {status['state'].get('error','okänt fel')}"

        if time.time() - start > timeout_s:
            return "⚠️ Horde tog för lång tid (>90 s). Försök igen senare."
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

# -------- kommandon -------------------------------------------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    """!ping  →  pong"""
    await ctx.send("pong")

# -------- on_message‑lyssnare ----------------------------------
@bot.event
async def on_message(message: discord.Message):
    # Låt commands‑systemet först
    await bot.process_commands(message)

    # Ignorera bots & DM:s
    if message.author.bot or isinstance(message.channel, discord.DMChannel):
        return

    # Om meddelandet börjar med '!' är det ett kommando: avbryt (slipper dubbel‑pong)
    if message.content.startswith(bot.command_prefix):
        return

    # Endast AI‑svar när "ove" nämns
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
