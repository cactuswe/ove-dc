# main.py – Discord‑bot som svarar via AI Horde när "ove" nämns
import os, time, logging, requests, asyncio, re, threading, http.server, socketserver, random
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
TRIGGER_REGEX = re.compile(r"\bove\b", re.I)

BASE_URL   = "https://aihorde.net/api/v2"
ASYNC_URL  = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"
MODELS_URL = f"{BASE_URL}/status/models?type=text"

# statisk reservlista om status‑kallet går ned
STATIC_FALLBACK = [
    "koboldcpp/FuseChat-Llama-3.2-1B-Instruct.Q8_0",
    "koboldcpp/google_gemma-3-1b-it-Q4_K_M",
    "koboldcpp/tinyllama",
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2.  Hitta bästa modell just nu
# --------------------------------------------------------------
def pick_best_model() -> str:
    try:
        data = requests.get(MODELS_URL, timeout=10).json()
        # sortera på queued först, sedan eta
        sorted_models = sorted(
            (m for m in data if m.get("count", 0) > 0),
            key=lambda m: (m.get("queued", 1e9), m.get("eta", 1e9)),
        )
        if sorted_models:
            best = sorted_models[0]
            logging.info("Väljer modell %s (queue=%s, eta=%s)",
                         best["name"], best["queued"], best["eta"])
            return best["name"]
    except Exception as e:
        logging.warning("Kunde inte hämta modell‑status: %s – använder reservlista", e)

    # pick random from fallback to undvika kö‑krock
    return random.choice(STATIC_FALLBACK)

# --------------------------------------------------------------
# 3.  AI Horde‑anrop
# --------------------------------------------------------------
def horde_infer(prompt: str, timeout_s: int = 90) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "⚠️ Jag behöver lite text att svara på 🙂"

    model = pick_best_model()
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
    headers = {"apikey": HORDE_KEY} if HORDE_KEY else {}

    try:
        r = requests.post(ASYNC_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        code = getattr(e.response, "status_code", "?")
        return f"⚠️ Horde‑fel {code}: {str(e)[:100]}"

    job = r.json()
    job_id = job.get("id")
    eta    = job.get("eta", "?")
    if eta != "?" and eta > timeout_s:
        return f"⏳ Kön ({eta//60} min) är längre än min maxgräns ({timeout_s}s). Försök om en stund!"

    start = time.time()
    while True:
        status = requests.get(STATUS_URL.format(id=job_id), timeout=30).json()

        state = status.get("state", {}).get("status")
        if state == "done":
            gens = status.get("generations", [])
            return gens[0]["text"].strip() if gens else "⚠️ Inget svar genererades."
        if state == "faulted":
            return f"⚠️ Horde avbröt jobbet: {status['state'].get('error','okänt fel')}"

        if time.time() - start > timeout_s:
            return "⚠️ Horde tog för lång tid (>90 s). Försök igen senare."
        time.sleep(1)

# --------------------------------------------------------------
# 4.  Discord‑bot
# --------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info("✅  %s online – guilds: %d", bot.user, len(bot.guilds))

@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.send("pong")

@bot.event
async def on_message(message: discord.Message):
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
# 5.  Starta boten
# --------------------------------------------------------------
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN saknas i miljön")
bot.run(DISCORD_TOKEN)
