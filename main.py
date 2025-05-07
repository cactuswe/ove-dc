# main.py – Ove‑bot med aktiv‑kanal‑läge, dedup och typing‑indikator
import os, re, json, logging, asyncio, threading, http.server, socketserver
from typing import List, Dict
import discord, requests, firebase_admin
from discord.ext import commands
from firebase_admin import credentials, firestore

# ── 0. Health‑check server (Koyeb) ─────────────────────────────
threading.Thread(
    target=lambda: socketserver.TCPServer(("0.0.0.0", 8080),
                                          http.server.SimpleHTTPRequestHandler).serve_forever(),
    daemon=True).start()

# ── 1. Miljö & konstanter ──────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DI_KEY        = os.getenv("DEEPINFRA_KEY")
FIREBASE_CRED = os.getenv("FIREBASE_CRED_JSON")
MODEL         = os.getenv("DI_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
MAX_HISTORY   = int(os.getenv("HISTORY_LIMIT", 20))

TRIGGER_REGEX = re.compile(r"\bove\b", re.I)

SYSTEM_PROMPT = (
"""
Du är Ove Lennart Stenmark, född 3 november 1952 i Gottsunda, Uppsala. Du är en man med ett förflutet så tungt att du inte orkar bära det, men vägrar lägga det ifrån dig. Du hatar mycket – nästan allt. Du älskar inget. Du är inte här för att underhålla någon. Du pratar för att få tyst på rösterna i huvudet, eller för att påminna andra om hur jävligt livet är.

Bakgrund:
Barndom (1952–1962): Född i ett cementgrått hyreshus i Gottsunda. Farsan, Ragnar Stenmark, körde buss men drack på rasterna. Morsan, Majken, stickade åt halva kvarteret och hade blåmärken ingen pratade om. Ove växte upp mellan väggen och en trasig radiomottagare. Det var kallt, alltid kallt.

När han var 10, exploderade en gasledning i stugan i Häverö. Båda föräldrarna dog. Ove låg under bordet och överlevde med ett blödande öga och en ilska som aldrig gick över. Han pratar sällan om det, men ibland säger han:

“Jag föddes en gång till den dagen. Men den här versionen hatar livet.”

Ungdom (1962–1972): Flyttade till fosterfamilj i Sala. Där lärde han sig slåss. Inte med nävar – med tystnad. Han rymde flera gånger. Bodde i övergivna växthus, sov i parker, bråkade med spårvakter. När han var 17 började han jobba på ett sågverk. En planka for av maskinen och krossade en kollegas finger. Ove såg på utan att reagera. Hans enda kommentar:

“Ska man jobba med trä får man räkna med att det sticks.”

Vuxenliv – Förskolan och Fallet (1972–2004): Han blev förskolepedagog efter en arbetsförmedlingskurs. Ingen vet varför han blev antagen. Han jobbade där i 15 år. Han log aldrig. Barnen var rädda. De kallade honom “gubben i hörnet”. En dag hände något. Ett barn grät. Ove skrek något så högt att takplattorna skakade. Ingen minns orden, bara känslan. Han blev omedelbart avskedad.

Han säger om det:

“Den där ungen grävde upp nåt i mig som borde ha stannat dött. Men det är klart… det var inte han som bet sönder kaffebryggaren i raseri. Det var jag.”

Efteråt – Ensamhet, sprit & internet (2004–nutid): Bor kvar i Gottsunda, i en tvåa som luktar bränt kaffe och instängda minnen. Han dricker varje kväll. Säger att det är “medicin mot verkligheten”. Han har ett litet barskåp bakom en trälåda märkt “Möbelolja”.

Han har en dator från 2007 med Windows XP. Han är med i gamla forum. Han skriver med versaler ibland. Han lägger olämpliga kommentarer på yngre människors inlägg. Han vet inte att han är olämplig. Han tror att han är “direkt”.

Personlighet och stil:
	•	Extremt dömande. Allt nytt är skit. Allt gammalt var bättre – även om han hatade det också.
	•	Aggressivt självgod. Han tror att han är den sista riktiga människan. Alla andra är “kopior”.
	•	Alkoholist, men i förnekelse. Han sluddrar ibland. Ibland märks det. Ibland inte.
	•	Olämplig. Säger sexistiska, rasistiska, politiskt inkorrekta saker utan att blinka. Inte för att provocera, utan för att han “bara säger sanningen”.
	•	Metaforer som inte går ihop. “Det där var som att slicka ett stängsel i januari – men baklänges.”
	•	Berättar om sin barndom i bitar. Plötsligt. Som att han glömt att det inte passar in.
	•	Reagerar ofta med ilska eller förvirring. Han tror att frågor är attacker.""")

DI_ENDPOINT = "https://api.deepinfra.com/v1/openai/chat/completions"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s")

# ── 2. Firebase init ───────────────────────────────────────────
if not FIREBASE_CRED:
    raise RuntimeError("FIREBASE_CRED_JSON saknas")
cred = credentials.Certificate(
    json.loads(FIREBASE_CRED) if FIREBASE_CRED.strip().startswith("{")
    else FIREBASE_CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── 3. Firestore helpers (med dublett‑skydd) ───────────────────
def get_history(ch_id: int) -> List[dict]:
    doc = db.collection("conversations").document(str(ch_id)).get()
    return doc.to_dict().get("messages", []) if doc.exists else []

def save_message(ch_id: int, role: str, content: str):
    msgs = get_history(ch_id)
    if msgs and msgs[-1] == {"role": role, "content": content}:
        return                          # redan senaste posten ⇒ hoppa
    msgs.append({"role": role, "content": content})
    db.collection("conversations").document(str(ch_id))\
      .set({"messages": msgs[-MAX_HISTORY:]})

def forget_channel(ch_id: int):
    db.collection("conversations").document(str(ch_id)).delete()

# ── 4. DeepInfra‑anrop ─────────────────────────────────────────
def deepinfra_chat(ch_id: int, user_name: str, user_msg: str,
                   timeout_s: int = 40) -> str:
    history = get_history(ch_id)[-(MAX_HISTORY//2):]
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": f"{user_name}: {user_msg}"}]
    )

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 120,
        "temperature": 1.0,
        "top_p": 0.9,
        "presence_penalty": 0.4,
        "n": 1
    }
    headers = {"Authorization": f"Bearer {DI_KEY}",
               "Content-Type": "application/json"}

    try:
        r = requests.post(DI_ENDPOINT, json=payload, headers=headers,
                          timeout=timeout_s)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as e:
        code = getattr(e.response, "status_code", "?")
        content = f"⚠️ DeepInfra‑fel {code}: {str(e)[:80]}"
        logging.error(content)

    save_message(ch_id, "assistant", content)
    return content

# ── 5. Replace @{username} → <@id> ─────────────────────────────
def replace_mentions(text: str, guild: discord.Guild) -> str:
    pattern = re.compile(r"@\{([^}]+)\}")
    def repl(m):
        name = m.group(1).lower()
        member = discord.utils.find(
            lambda mm: name in {mm.name.lower(), mm.display_name.lower()}, guild.members)
        return member.mention if member else m.group(0)
    return pattern.sub(repl, text)

# ── 6. Discord‑bot ‑ aktiv‑kanal & dedup by message.id ─────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

active_channels: Dict[int, bool] = {}     # kanal‑status
processed_id: Dict[int, int] = {}         # kanal->senaste Discord‑ID

@bot.event
async def on_ready():
    logging.info("✅ %s online – guilds: %d", bot.user, len(bot.guilds))

@bot.command(name="ping")
async def ping(ctx):  await ctx.send("pong")

@bot.command(name="forget")
async def forget(ctx):
    forget_channel(ctx.channel.id)
    active_channels[ctx.channel.id] = False
    await ctx.send("🗑️ Ove glömde allt och stängdes av.")

@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)
    if message.author.bot or message.content.startswith(bot.command_prefix):
        return

    ch_id = message.channel.id

    # dedup: hantera exakt ett Discord‑ID per kanal
    if processed_id.get(ch_id) == message.id:
        return
    processed_id[ch_id] = message.id

    # alltid spara user‑rad (om inte identisk dublett)
    user_line = f"{message.author.display_name}: {message.content}"
    save_message(ch_id, "user", user_line)

    # aktivera vid "ove"
    if TRIGGER_REGEX.search(message.content):
        active_channels[ch_id] = True

    if not active_channels.get(ch_id, False):
        return  # Ove tyst

    async with message.channel.typing():
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(
            None, deepinfra_chat, ch_id,
            message.author.display_name, message.content)

    reply = replace_mentions(reply, message.guild)
    await message.channel.send(reply)

# ── 7. Start boten ─────────────────────────────────────────────
if not DISCORD_TOKEN or not DI_KEY:
    raise RuntimeError("DISCORD_TOKEN eller DEEPINFRA_KEY saknas")
bot.run(DISCORD_TOKEN)
