# main.py – Discord‑bot som svarar via AI Horde när "ove" nämns
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
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HORDE_KEY     = os.getenv("HORDE_KEY", "")

TRIGGER_REGEX = re.compile(r"\bove\b", re.I)          # ord‑trigger

# Fall‑back‑lista: första modellen med ledig worker används
MODEL_CANDIDATES = [
    "koboldcpp/FuseChat-Llama-3.2-1B-Instruct.Q8_0",
    "koboldcpp/google_gemma-3-1b-it-Q4_K_M",
    "koboldcpp/tinyllama",
]

BASE_URL   = "https://aihorde.net/api/v2"
ASYNC_URL  = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2.  AI Horde‑anrop med modell‑fallback och kö‑info
# --------------------------------------------------------------
def horde_infer(prompt: str, timeout_s: int = 90) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "⚠️ Jag behöver lite text att svara på 🙂"

    headers = {"apikey": HORDE_KEY} if HORDE_KEY else {}

    # Prova varje modell i listan tills en ger rimlig ETA
    for model in MODEL_CANDIDATES:
        payload = {
            "prompt": prompt,
            "max_tokens": 120,
            "models": [model],
            "params": {
                "temperature": 0.8,
                "top_p": 0.95,
                "max_context_length": 2048,
            },
        }
        try:
            r = requests.post(ASYNC_URL, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            logging.warning("POST‑fel på %s: %s", model, e)
            continue  # prova nästa modell

        job = r.json()
        job_id = job.get("id")
        eta = job.get("eta", "?")

        # Hoppa till nästa modell om ETA är längre än timeout
        if eta != "?" and eta > timeout_s:
            logging.info("%s kö‑ETA %ss – provar annan modell", model, eta)
            continue

        # Poll‑loop
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

    # Om ingen modell gav rimlig ETA eller POST lyckades
    return "⏳ Alla modeller är hårt belastade just nu – försök igen om en stund!"

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
    """!ping  → pong"""
    await ctx.send("pong")

# -------- on_message‑lyssnare ---------------------------------
@bot.event
async def on_message(message: discord.Message):
    # Låt commands‑systemet köra först
    await bot.process_commands(message)

    if message.author.bot or isinstance(message.channel, discord.DMChannel):
        return
    if message.content.startswith(bot.command_prefix):
        return

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
