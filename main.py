# main.py – Discord‑bot som svarar via DeepInfra när "ove" nämns
import os, time, logging, requests, asyncio, re, threading, http.server, socketserver
import discord
from discord.ext import commands

# --------------------------------------------------------------
# 0. Mini‑HTTP‑server för Koyebs health‑check
# --------------------------------------------------------------
threading.Thread(
    target=lambda: socketserver.TCPServer(("0.0.0.0", 8080),
                                          http.server.SimpleHTTPRequestHandler).serve_forever(),
    daemon=True).start()

# --------------------------------------------------------------
# 1. Konfiguration
# --------------------------------------------------------------
DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
DI_KEY         = os.getenv("DEEPINFRA_KEY")
MODEL          = os.getenv("DI_MODEL",
    "cognitivecomputations/dolphin-2.9.1-llama-3-70b")  # känd “uncensored”‑modell
TRIGGER_REGEX  = re.compile(r"\bove\b", re.I)

DI_ENDPOINT = "https://api.deepinfra.com/v1/openai/chat/completions"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# --------------------------------------------------------------
# 2. DeepInfra‑anrop
# --------------------------------------------------------------
def deepinfra_chat(prompt: str, timeout_s: int = 30) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "⚠️ Jag behöver lite text att svara på 🙂"

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 120,
        "temperature": 0.8,
        "top_p": 0.95,
    }
    headers = {
        "Authorization": f"Bearer {DI_KEY}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(DI_ENDPOINT, json=payload, headers=headers, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.RequestException as e:
        code = getattr(e.response, "status_code", "?")
        txt  = getattr(e.response, "text", str(e))[:120]
        logging.error("DeepInfra‑fel %s: %s", code, txt)
        return f"⚠️ DeepInfra‑fel {code}: {txt}"

# --------------------------------------------------------------
# 3. Discord‑bot
# --------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info("✅ %s online – guilds: %d", bot.user, len(bot.guilds))

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
        reply = await loop.run_in_executor(None, deepinfra_chat, message.content)
        await message.channel.send(reply)

# --------------------------------------------------------------
# 4. Starta boten
# --------------------------------------------------------------
if not DISCORD_TOKEN or not DI_KEY:
    raise RuntimeError("DISCORD_TOKEN eller DEEPINFRA_KEY saknas i miljön")
bot.run(DISCORD_TOKEN)
