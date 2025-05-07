import os, time, requests, discord, asyncio
from discord.ext import commands

HORDE_KEY = os.getenv("HORDE_KEY", "")

BASE_URL = "https://aihorde.net/api/v2"
ASYNC_URL = f"{BASE_URL}/generate/text/async"
STATUS_URL = f"{BASE_URL}/generate/text/status/{{id}}"

def horde_infer(prompt: str) -> str:
    payload = {
        "prompt": prompt,
        "params": {"temperature": 0.8, "top_p": 0.95, "max_context_length": 2048},
        "models": ["Pygmalion-2-7b"],
        "max_tokens": 120,
    }
    headers = {"apikey": HORDE_KEY} if HORDE_KEY else {}

    # 1 – submit job
    job = requests.post(ASYNC_URL, json=payload, headers=headers, timeout=30)
    job.raise_for_status()
    job_id = job.json()["id"]

    # 2 – poll until finished
    while True:
        status = requests.get(STATUS_URL.format(id=job_id), timeout=30).json()
        if status["state"]["status"] == "done":
            return status["generations"][0]["text"].strip()
        time.sleep(1)              # blocking sleep is fine here

# --- Discord wiring ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    loop = asyncio.get_running_loop()
    reply = await loop.run_in_executor(None, horde_infer, msg.content)
    await msg.channel.send(reply)

bot.run(os.getenv("DISCORD_TOKEN"))