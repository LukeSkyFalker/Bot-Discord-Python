import discord
import json, os, asyncio, random, time, aiofiles, re, asyncpraw, difflib, html
from collections import deque
from datetime import datetime as dt
from zoneinfo import ZoneInfo
from functools import wraps
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed, SelectOption, ButtonStyle, Object
from discord.ui import Select, Button, View, Modal, TextInput
from pathlib import Path
from typing import List, Any
from dotenv import load_dotenv
load_dotenv()
ITALY_TZ = ZoneInfo("Europe/Rome")

# ========================
# CONFIG
# ========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="/", intents=intents)
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN non trovato nel file .env")

# ========================
# VARIABILI GLOBALI
# ========================
user_temp_channels = {}
task_attivo = False
stats_lock = asyncio.Lock()
voice_lock = asyncio.Lock()
counting_lock = asyncio.Lock()
data = {}
user_lancio_cd = {}
user_cooldowns = {}

# ========================
# CARICAMENTO SICURO DEGLI ID (CONVERSIONE IN INTERI)
# ========================
def get_int_env(key: str) -> int | None:
    """Legge una variabile d'ambiente e la converte in intero. Restituisce None se mancante."""
    val = os.getenv(key)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        print(f"⚠️ ERRORE: la variabile d'ambiente {key}='{val}' non è un numero valido!")
        return None

GUILD_ID = get_int_env("GUILD_ID")
WELCOME_CHANNEL_ID = get_int_env("WELCOME_CHANNEL_ID")
GOODBYE_CHANNEL_ID = get_int_env("GOODBYE_CHANNEL_ID")
TICKET_CHANNEL = get_int_env("TICKET_CHANNEL")
LOG_CHANNEL_ID = get_int_env("LOG_CHANNEL_ID")
TICKET_LOG_ID = get_int_env("TICKET_LOG_ID")
TEMP_VOICE_VOC_ID = get_int_env("TEMP_VOICE_VOC_ID")
CATEGORY_STATS_ID = get_int_env("CATEGORY_STATS_ID")
CATEGORY_TICKET_ID = get_int_env("CATEGORY_TICKET_ID")
PING_STAFF_ROLE_ID = get_int_env("PING_STAFF_ROLE_ID")
STAFF_ROLE_ID = get_int_env("STAFF_ROLE_ID")
OPEN_TICKET_ROLE_ID = get_int_env("OPEN_TICKET_ROLE_ID")
COUNTING_ID = get_int_env("COUNTING_ID")
OWNER_ID = get_int_env("OWNER_ID")

# ========================
# RATE LIMITING
# ========================
class RateLimiter:
    def __init__(self, max_calls=45, period=1.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self.lock = asyncio.Lock()

    async def wait_if_needed(self):
        async with self.lock:
            now = time.time()
            while self.calls and now - self.calls[0] > self.period:
                self.calls.popleft()
            if len(self.calls) >= self.max_calls:
                wait_time = self.period - (now - self.calls[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            self.calls.append(time.time())

def rate_limited():
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            await api_limiter.wait_if_needed()
            return await func(*args, **kwargs)
        return wrapper
    return decorator

api_limiter = RateLimiter(max_calls=45, period=1.0)

async def safe_api_call(func, *args, **kwargs):
    await api_limiter.wait_if_needed()
    return await func(*args, **kwargs)

# ========================
# FILE DI SALVATAGGIO UNICO
# ========================
DATA_FILE = "bot_data.json"
DEFAULT_DATA = {
    "stats": {},
    "logs": {},
    "counting": {},
    "ticket_panel": {"ticket_panel_msg_id": None},
    "reaction_roles": []
}

# ========================
# GESTIONE JSON
# ========================
async def load_data():
    if os.path.exists(DATA_FILE):
        async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                loaded_data = json.loads(await f.read())
                for key, value in DEFAULT_DATA.items():
                    if key not in loaded_data:
                        loaded_data[key] = value
                if not isinstance(loaded_data.get("reaction_roles"), list):
                    print("⚠️ reaction_roles corrotto nel JSON, ripristino...")
                    loaded_data["reaction_roles"] = []
                clean_reaction_roles = []
                for item in loaded_data["reaction_roles"]:
                    if not isinstance(item, dict):
                        print(f"⚠️ Elemento reaction_roles non valido rimosso: {item}")
                        continue
                    if "role_id" in item and "role_ids" not in item:
                        item["role_ids"] = [item["role_id"]]
                        del item["role_id"]
                    if all(k in item for k in ["guild_id", "channel_id", "message_id", "emoji", "role_ids"]):
                        if not isinstance(item.get("role_ids"), list):
                            item["role_ids"] = [item["role_ids"]]
                        clean_reaction_roles.append(item)
                    else:
                        print(f"⚠️ Elemento reaction_roles non valido rimosso: {item}")
                loaded_data["reaction_roles"] = clean_reaction_roles
                for key in ["stats", "logs", "counting"]:
                    if not isinstance(loaded_data.get(key), dict):
                        print(f"⚠️ {key} corrotto nel JSON, ripristino...")
                        loaded_data[key] = {}
                return loaded_data
            except (json.JSONDecodeError, TypeError) as e:
                print(f"⚠️ JSON corrotto, uso i default: {e}")
                return DEFAULT_DATA.copy()
    return DEFAULT_DATA.copy()

async def save_data(data_to_save):
    async with aiofiles.open(DATA_FILE + ".tmp", "w", encoding="utf-8") as f:
        await f.write(json.dumps(data_to_save, indent=4, ensure_ascii=False))
    os.replace(DATA_FILE + ".tmp", DATA_FILE)

# ========================
# INIZIALIZZAZIONE
# ========================
async def init():
    global data
    data = await load_data()

# ========================
# UTILITÀ
# ========================
def log_footer():
    return dt.now(ITALY_TZ).strftime("%d/%m/%Y alle %H:%M")

def sanitize_channel_name(name: str) -> str:
    name = re.sub(r'[^a-z0-9-]', '-', name.lower())
    name = re.sub(r'-+', '-', name).strip('-')
    return name[:100] or "ticket"

# ========================
# /SOCIAL
# ========================
class SocialButtons(View):
    def __init__(self):
        super().__init__(timeout=None)
        # Inserisci qui i tuoi link reali nel file .env oppure modifica direttamente qui
        self.add_item(Button(label="Youtube", url=os.getenv("SOCIAL_YOUTUBE", "https://example.com/youtube")))
        self.add_item(Button(label="Twitch", url=os.getenv("SOCIAL_TWITCH", "https://example.com/twitch")))
        self.add_item(Button(label="Instagram", url=os.getenv("SOCIAL_INSTAGRAM", "https://example.com/instagram")))
        self.add_item(Button(label="TikTok", url=os.getenv("SOCIAL_TIKTOK", "https://example.com/tiktok")))
        self.add_item(Button(label="Donazione", url=os.getenv("SOCIAL_DONATE", "https://example.com/donate")))

@bot.tree.command(name="social", description="Mostra i link ai social e alla pagina di donazione.", guild=Object(id=GUILD_ID))
async def social(interaction: Interaction):
    embed = Embed(
        title="I nostri Social e Donazioni",
        description="Clicca i bottoni qui sotto per visitare i nostri social o effettuare una donazione!",
        color=0xc4302b
    )
    embed.set_footer(text="Lo Staff")
    await interaction.response.send_message(embed=embed, view=SocialButtons(), ephemeral=True)

# ========================
# /ANNUNCIO
# ========================
@bot.tree.command(name="annuncio", description="Invia un annuncio in un canale specifico", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def annuncio(interaction: discord.Interaction, canale: discord.TextChannel, titolo: str, messaggio: str, colore: str = None):
    try:
        color = discord.Color(int(colore.strip("#"), 16)) if colore else discord.Color.blue()
    except ValueError:
        color = discord.Color.blue()
    embed = discord.Embed(title=titolo, description=messaggio, color=color, timestamp=dt.now(ITALY_TZ))
    embed.set_footer(text="Lo Staff")
    await canale.send(embed=embed)
    await interaction.response.send_message("Annuncio inviato!", ephemeral=True)

# ========================
# /CLEAR
# ========================
@bot.tree.command(name="clear", description="Elimina i messaggi", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 1:
        await interaction.response.send_message("Devi inserire almeno 1 messaggio.", ephemeral=True)
        return
    if amount > 100:
        await interaction.response.send_message("Troppi messaggi! Il massimo è 100.", ephemeral=True)
        return
    await interaction.response.send_message("Pulizia in corso...", ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Ho eliminato {len(deleted)} messaggi.", ephemeral=True)
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = Embed(
            title="🧹 Clear Eseguito",
            description=f"{interaction.user.mention} ha eliminato {len(deleted)} messaggi.",
            color=discord.Color.orange(),
            timestamp=dt.now(ITALY_TZ)
        )
        embed.add_field(name="Canale", value=interaction.channel.mention, inline=False)
        embed.add_field(name="Eseguito da", value=interaction.user.mention, inline=False)
        embed.set_footer(text="Lo Staff")
        await safe_api_call(log_channel.send, embed=embed)

# ========================
# /SETLOG
# ========================
@bot.tree.command(name="setlog", description="Configura il canale dei log", guild=Object(id=GUILD_ID))
@app_commands.describe(channel="Menziona il canale per i log")
@app_commands.checks.has_permissions(administrator=True)
async def setlog(interaction: Interaction, channel: discord.TextChannel):
    data["logs"][str(interaction.guild_id)] = channel.id
    await save_data(data)
    embed = Embed(
        title="Log Configurato",
        description=f"Canale log impostato su {channel.mention}",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Lo Staff • {log_footer()}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setlog.error
async def setlog_error(interaction: Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        embed = Embed(
            title="Permesso Negato",
            description="Solo gli amministratori possono configurare il canale dei log.",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Lo Staff • {log_footer()}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

def get_log_channel(guild_id):
    return data.get("logs", {}).get(str(guild_id))

# ========================
# EVENTI DI LOGGING
# ========================
@bot.event
async def on_member_join(member):
    log_channel_id = get_log_channel(member.guild.id)
    if log_channel_id:
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            embed = Embed(title="Membro Entrato", description=f"{member.mention} è entrato nel server.", color=discord.Color.green())
            embed.set_footer(text=f"Lo Staff • {log_footer()}")
            await safe_api_call(log_channel.send, embed=embed)
    if str(member.guild.id) in data.get("stats", {}):
        await aggiorna_statistiche(member.guild)
    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        welcome_embed = Embed(
            title=f"Benvenuto {member.display_name}",
            description=(
                "> Ciao, leggi le regole del server!\n"
                "> Personalizza il tuo profilo con dei semplici ruoli.\n"
                "> Dopo di ciò, potrai esplorare e conoscere tutti quanti."
            ),
            color=discord.Color.blue()
        )
        welcome_embed.set_thumbnail(url=member.display_avatar.url)
        welcome_embed.set_footer(text="Lo Staff")
        await welcome_channel.send(embed=welcome_embed)

@bot.event
async def on_member_remove(member):
    log_channel_id = get_log_channel(member.guild.id)
    if log_channel_id:
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            embed = Embed(title="Membro Uscito", description=f"{member.mention} ha lasciato il server.", color=discord.Color.red())
            embed.set_footer(text=f"Lo Staff • {log_footer()}")
            await safe_api_call(log_channel.send, embed=embed)
    if str(member.guild.id) in data.get("stats", {}):
        await aggiorna_statistiche(member.guild)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    log_channel_id = get_log_channel(before.guild.id)
    if not log_channel_id:
        return
    log_channel = before.guild.get_channel(log_channel_id)
    if not log_channel:
        return
    embed = Embed(title="📝 Messaggio Modificato", color=discord.Color.orange())
    embed.add_field(name="Autore", value=before.author.mention, inline=True)
    embed.add_field(name="Canale", value=before.channel.mention, inline=True)
    embed.add_field(name="Prima", value=before.content[:1024] or "*[vuoto]*", inline=False)
    embed.add_field(name="Dopo", value=after.content[:1024] or "*[vuoto]*", inline=False)
    embed.set_footer(text=f"Lo Staff • {log_footer()}")
    await safe_api_call(log_channel.send, embed=embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    log_channel_id = get_log_channel(message.guild.id)
    if not log_channel_id:
        return
    log_channel = message.guild.get_channel(log_channel_id)
    if not log_channel:
        return
    is_link = any(x in message.content for x in ["http://", "https://", "www."])
    embed = Embed(
        title="🔗 Messaggio Eliminato" if is_link else "🗑️ Messaggio Eliminato",
        color=discord.Color.purple() if is_link else discord.Color.red()
    )
    embed.add_field(name="Autore", value=message.author.mention, inline=True)
    embed.add_field(name="Canale", value=message.channel.mention, inline=True)
    embed.add_field(name="Contenuto", value=message.content[:1024] or "*[vuoto]*", inline=False)
    if is_link:
        embed.description = "⚠️ Questo messaggio conteneva un link."
    embed.set_footer(text=f"Lo Staff • {log_footer()}")
    await safe_api_call(log_channel.send, embed=embed)

@bot.event
async def on_member_update(before, after):
    if before.nick != after.nick:
        log_channel_id = get_log_channel(before.guild.id)
        if not log_channel_id:
            return
        log_channel = before.guild.get_channel(log_channel_id)
        if not log_channel:
            return
        embed = Embed(title="✏️ Soprannome Modificato", color=discord.Color.gold())
        embed.add_field(name="Utente", value=after.mention, inline=True)
        embed.add_field(name="Prima", value=before.nick or before.name, inline=True)
        embed.add_field(name="Dopo", value=after.nick or after.name, inline=True)
        embed.set_footer(text=f"Lo Staff • {log_footer()}")
        await safe_api_call(log_channel.send, embed=embed)

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    log_channel_id = get_log_channel(guild.id)
    log_channel = guild.get_channel(log_channel_id) if log_channel_id else None
    deleter = None
    async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
        if entry.target.id == channel.id:
            time_diff = (discord.utils.utcnow() - entry.created_at).total_seconds()
            if time_diff < 10:
                deleter = entry.user
                break
    if log_channel:
        embed = Embed(
            title="🗑️ Canale Eliminato",
            description=(
                f"**Canale:** {channel.name}\n"
                f"**Tipo:** {'Vocale' if isinstance(channel, discord.VoiceChannel) else 'Testuale'}\n"
                f"**Eliminato da:** {deleter.mention if deleter else 'Sconosciuto'}"
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text=f"Lo Staff • {log_footer()}")
        await safe_api_call(log_channel.send, embed=embed)

@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        guild = after.guild
        log_channel_id = get_log_channel(guild.id)
        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None
        rinominato_da = "Sconosciuto"
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_update):
            if entry.target.id == after.id:
                rinominato_da = entry.user.mention
                break
        if log_channel:
            embed = Embed(
                title="✏️ Canale Rinominato",
                description=(
                    f"**Vecchio nome:** `{before.name}`\n"
                    f"**Nuovo nome:** `{after.name}`\n"
                    f"**Tipo:** {'Vocale' if isinstance(after, discord.VoiceChannel) else 'Testuale'}\n"
                    f"**Rinominato da:** {rinominato_da}"
                ),
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Lo Staff • {log_footer()}")
            await safe_api_call(log_channel.send, embed=embed)

# ========================
# CANALI TEMPORANEI
# ========================
@bot.event
async def on_voice_state_update(member, before, after):
    global user_temp_channels
    log_channel = bot.get_channel(data.get("logs", {}).get(str(member.guild.id)))
    if log_channel:
        titolo = colore = descrizione = None
        if before.channel is None and after.channel:
            titolo, colore = "🔊 Entrata Canale Vocale", discord.Color.green()
            descrizione = f"{member.mention} è entrato in {after.channel.mention}"
        elif before.channel and after.channel and before.channel != after.channel:
            titolo, colore = "↔️ Spostamento Canale Vocale", discord.Color.orange()
            descrizione = f"{member.mention} si è spostato da {before.channel.mention} a {after.channel.mention}"
        elif before.channel and after.channel is None:
            titolo, colore = "⏹️ Uscita Canale Vocale", discord.Color.red()
            descrizione = f"{member.mention} ha lasciato {before.channel.mention}"
        if titolo:
            embed = discord.Embed(title=titolo, description=descrizione, color=colore)
            embed.set_footer(text=f"Lo Staff • {log_footer()}")
            await safe_api_call(log_channel.send, embed=embed)

    if after.channel and after.channel.id == TEMP_VOICE_VOC_ID:
        async with voice_lock:
            temp_channel = None
            try:
                overwrites = {
                    member.guild.default_role: discord.PermissionOverwrite(connect=False),
                    member: discord.PermissionOverwrite(connect=True, speak=True, manage_channels=True)
                }
                staff_role = member.guild.get_role(STAFF_ROLE_ID)
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(connect=True, speak=True)
                temp_channel = await member.guild.create_voice_channel(
                    name=f"🔊 {member.display_name}",
                    category=after.channel.category,
                    overwrites=overwrites,
                    user_limit=5
                )
                await member.move_to(temp_channel)
                user_temp_channels[member.id] = temp_channel.id
            except Exception:
                if temp_channel:
                    await temp_channel.delete()

    if before.channel and before.channel.id in user_temp_channels.values() and len(before.channel.members) == 0:
        async with voice_lock:
            try:
                await before.channel.delete()
            except Exception:
                pass
            user_temp_channels = {uid: cid for uid, cid in user_temp_channels.items() if cid != before.channel.id}

# ========================
# SALVATAGGIO TICKET IN HTML
# ========================
def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\|?*]', '', name)

def _generate_html(user: Any, staff: Any, motivo: str, messages: List[Any], scelta: str = "Generale") -> str:
    now = dt.now(ITALY_TZ)
    date_str = now.strftime("%d/%m/%Y %H:%M")
    if hasattr(user, 'id') and hasattr(user, 'name'):
        name = getattr(user, 'display_name', None) or user.name
        user_safe = f"{html.escape(name)} ({user.id})"
    else:
        user_safe = html.escape(str(user))
    staff_safe = html.escape(str(staff))
    msgs_html = []
    for msg in reversed(messages):
        content_text = msg.content if msg.content else "*[Solo allegati o messaggio vuoto]*"
        content_safe = html.escape(content_text).replace("\n", "<br>")
        msg_date = msg.created_at.astimezone(ITALY_TZ).strftime("%d/%m/%Y %H:%M")
        author_name = getattr(msg.author, 'display_name', None) or msg.author.name
        author_id = getattr(msg.author, 'id', 'Sconosciuto')
        author_safe = f"{html.escape(str(author_name))} ({author_id})"
        attachments_html = ""
        if msg.attachments:
            attachments_html = "<div class='attachments'>"
            for att in msg.attachments:
                is_image = any(att.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'])
                if is_image:
                    attachments_html += f"""
                    <div class="attachment-item">
                        <a href="{att.url}" target="_blank">
                            <img src="{att.url}" alt="{html.escape(att.filename)}" class="attachment-img">
                        </a>
                        <br>
                        <a href="{att.url}" target="_blank" class="file-link">📎 Scarica: {html.escape(att.filename)}</a>
                    </div>
                    """
                else:
                    attachments_html += f"""
                    <div class="attachment-item">
                        <a href="{att.url}" target="_blank" class="file-link">📎 Scarica: {html.escape(att.filename)}</a>
                    </div>
                    """
            attachments_html += "</div>"
        msgs_html.append(f"""
        <div class="msg">
            <div class="msg-header">
                <span class="author">{author_safe}</span>
                <span class="datetime">{msg_date}</span>
            </div>
            <div class="content">{content_safe}</div>
            {attachments_html}
        </div>
        """)
    logo_url = os.getenv("COMMUNITY_LOGO_URL", "https://example.com/logo.png")
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" href="{logo_url}">
    <title>Richiesta di {html.escape(scelta)} - {date_str}</title>
    <style>
        :root {{ --bg: #f4f4f9; --text: #333; --msg-bg: #fff; --border: #ddd; --accent: #007acc; --link-bg: #e9ecef; }}
        @media (prefers-color-scheme: dark) {{
            :root {{ --bg: #1a1a1a; --text: #e0e0e0; --msg-bg: #2d2d2d; --border: #444; --link-bg: #3a3a3a; }}
        }}
        body {{ font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 20px; line-height: 1.6; text-align: center; }}
        .container {{ max-width: 900px; margin: 0 auto; background: var(--msg-bg); padding: 30px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
        h1 {{ border-bottom: 3px solid var(--accent); padding-bottom: 5px; display: inline-block; }}
        .logo {{ width: 110px; margin: 0 auto 20px auto; display: block; border-radius: 12px; }}
        .info-grid {{ display: inline-grid; text-align: center; gap: 12px; margin: 20px auto; background: rgba(0,0,0,0.05); padding: 20px; border-radius: 8px; }}
        .info-row {{ display: flex; justify-content: center; gap: 10px; align-items: center; }}
        .msg {{ margin: 16px auto; padding: 16px; border: 1px solid var(--border); background: rgba(0,0,0,0.02); border-radius: 8px; text-align: left; word-wrap: break-word; }}
        .msg-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
        .author {{ font-weight: bold; color: var(--accent); font-size: 1.1em; }}
        .datetime {{ color: #888; font-size: 0.85em; font-family: monospace; }}
        .content {{ white-space: pre-wrap; word-wrap: break-word; }}
        .attachments {{ margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); }}
        .attachment-item {{ margin-bottom: 10px; }}
        .attachment-img {{ max-width: 100%; max-height: 400px; border-radius: 8px; margin-top: 5px; cursor: pointer; border: 1px solid var(--border); }}
        .file-link {{ display: inline-flex; align-items: center; gap: 6px; background: var(--link-bg); color: var(--text); padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 0.9em; font-weight: 500; margin-top: 5px; transition: background 0.2s; }}
        .file-link:hover {{ background: var(--accent); color: white; }}
        hr {{ border: 0; border-top: 2px solid var(--border); margin: 25px auto; width: 50%; }}
        h2 {{ display: inline-block; border-bottom: 2px solid var(--accent); padding-bottom: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <img src="{logo_url}" alt="Logo" class="logo">
        <h1>Richiesta di {html.escape(scelta)}</h1>
        <br>
        <div class="info-grid">
            <div class="info-row"><strong>Utente:</strong> <span>{user_safe}</span></div>
            <div class="info-row"><strong>Staff:</strong> <span>{staff_safe}</span></div>
            <div class="info-row"><strong>Motivo:</strong> <span>{html.escape(motivo)}</span></div>
            <div class="info-row"><strong>Categoria:</strong> <span>{html.escape(scelta)}</span></div>
            <div class="info-row"><strong>Data Chiusura:</strong> <span>{date_str}</span></div>
        </div>
        <br>
        <h2>Cronologia Messaggi</h2>
        <div class="messages-container">{''.join(msgs_html)}</div>
    </div>
</body>
</html>"""

async def salva_ticket_html(channel, user, staff, motivo, messages, scelta: str):
    safe_channel_name = sanitize_filename(channel.name)
    timestamp = dt.now(ITALY_TZ).strftime('%Y%m%d%H%M')
    filename = f"ticket_{safe_channel_name}_{timestamp}.html"
    file_path = Path(filename)
    html_content = _generate_html(user, staff, motivo, messages, scelta)
    await asyncio.to_thread(file_path.write_text, html_content, encoding="utf-8")
    return file_path

# ========================
# SISTEMA TICKET
# ========================
def build_ticket_overwrites(guild, user):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    staff_role = guild.get_role(PING_STAFF_ROLE_ID)
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, manage_messages=True, manage_channels=True
        )
    return overwrites

class CloseButton(Button):
    def __init__(self):
        super().__init__(label="Chiudi Ticket", emoji="🔒", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: Interaction):
        staff_role = interaction.guild.get_role(PING_STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Solo lo staff può chiudere i ticket.", ephemeral=True)
            return
        modal = CloseTicketModal(channel_to_close=interaction.channel)
        try:
            await interaction.response.send_modal(modal)
        except Exception:
            await interaction.followup.send("❌ Impossibile aprire il modal.", ephemeral=True)

class CloseTicketModal(Modal, title="Chiudi Ticket"):
    reason = TextInput(
        label="Motivo della chiusura",
        style=discord.TextStyle.paragraph,
        placeholder="Inserisci il motivo...",
        required=True,
        max_length=50
    )

    def __init__(self, channel_to_close):
        super().__init__(timeout=None)
        self.channel_to_close = channel_to_close

    async def on_submit(self, interaction: Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        reason = self.reason.value
        log_channel = bot.get_channel(TICKET_LOG_ID)
        messages = [msg async for msg in self.channel_to_close.history(limit=200)]
        topic_parts = self.channel_to_close.topic.split("|") if self.channel_to_close.topic else []
        user_id = int(topic_parts[0]) if topic_parts and topic_parts[0].isdigit() else None
        scelta = topic_parts[1] if len(topic_parts) > 1 else "Generale"
        user_display = "Utente sconosciuto"
        if user_id:
            try:
                user_obj = await bot.fetch_user(user_id)
                name = getattr(user_obj, 'display_name', None) or user_obj.name
                user_display = f"{name} ({user_id})"
            except Exception:
                user_display = f"Utente ID: {user_id}"
        html_file = await salva_ticket_html(self.channel_to_close, user_display, interaction.user, reason, messages, scelta)
        if log_channel:
            embed = Embed(
                title="🔒 Ticket Chiuso",
                description=(
                    f"**Staff:** {interaction.user.mention}\n"
                    f"**Canale:** {self.channel_to_close.name}\n"
                    f"**Motivo:** {reason}\n"
                    f"**Utente:** {user_display}"
                ),
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Lo Staff • {log_footer()}")
            try:
                with open(html_file, "rb") as f:
                    await log_channel.send(embed=embed, file=discord.File(f, filename=html_file.name))
                os.remove(html_file)
            except Exception as e:
                await safe_api_call(log_channel.send, embed=embed)
                print(f"❌ Errore invio HTML: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("✅ Ticket chiuso e archiviato.", ephemeral=True)
        else:
            await interaction.followup.send("✅ Ticket chiuso e archiviato.", ephemeral=True)
        await asyncio.sleep(0.5)
        try:
            if self.channel_to_close.permissions_for(interaction.guild.me).manage_channels:
                await self.channel_to_close.delete()
            else:
                print("❌ Non ho permessi per cancellare il canale")
        except Exception as e:
            print(f"❌ Errore nella cancellazione del canale: {e}")

class TicketSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="Assistenza Generale", emoji="🛠️", value="Assistenza Generale"),
            SelectOption(label="Shop", emoji="🛍️", value="Shop"),
            SelectOption(label="Segnalazione", emoji="⚠️", value="Segnalazione"),
            SelectOption(label="Candidatura Staff", emoji="👥", value="Candidatura Staff")
        ]
        super().__init__(placeholder="Apri un ticket...", min_values=1, max_values=1, options=options, custom_id="ticket_select")

    async def callback(self, interaction: Interaction):
        guild = interaction.guild
        category = guild.get_channel(CATEGORY_TICKET_ID)
        scelta = self.values[0]
        if not category:
            await interaction.response.send_message("❌ Categoria ticket non trovata", ephemeral=True)
            return
        existing = discord.utils.get(category.text_channels, topic=str(interaction.user.id))
        if existing:
            await interaction.response.send_message(f"Hai già un ticket aperto: {existing.mention}", ephemeral=True)
            return
        overwrites = build_ticket_overwrites(guild, interaction.user)
        new_channel = await guild.create_text_channel(
            name=sanitize_channel_name(f"ticket-{interaction.user.name}"),
            category=category,
            overwrites=overwrites,
            topic=f"{interaction.user.id}|{scelta}"
        )
        embed = Embed(
            title="Richiesta di supporto",
            description=f"La tua richiesta è stata aperta.\nTipo: {scelta}\nAttendi risposta dallo staff.",
            color=discord.Color.red()
        )
        view = View(timeout=None)
        view.add_item(CloseButton())
        staff_role = guild.get_role(PING_STAFF_ROLE_ID)
        await new_channel.send(
            content=f"{staff_role.mention if staff_role else ''} {interaction.user.mention}",
            embed=embed,
            view=view
        )
        await interaction.response.send_message(f"✅ Ticket creato: {new_channel.mention}", ephemeral=True)

class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

async def setup_ticket_panel():
    channel = bot.get_channel(TICKET_CHANNEL)
    if not channel:
        return
    embed = Embed(
        title="📩 Supporto",
        description="Se hai bisogno di supporto clicca qui sotto e apri un ticket.",
        color=discord.Color.blue()
    )
    embed.set_footer(text="Lo Staff")
    view = TicketPanelView()
    async for msg in channel.history(limit=20):
        if msg.author == bot.user and len(msg.embeds) > 0 and msg.embeds[0].title == "📩 Supporto":
            try:
                await msg.edit(embed=embed, view=view)
                return
            except Exception:
                pass
    await channel.send(embed=embed, view=view)

# ========================
# /LANCIO
# ========================
class TestaButton(Button):
    def __init__(self):
        super().__init__(label="Testa", style=ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        await handle_lancio(interaction, "Testa", self.view)

class CroceButton(Button):
    def __init__(self):
        super().__init__(label="Croce", style=ButtonStyle.secondary)

    async def callback(self, interaction: Interaction):
        await handle_lancio(interaction, "Croce", self.view)

class TestaCroceView(View):
    def __init__(self):
        super().__init__(timeout=30)
        self.add_item(TestaButton())
        self.add_item(CroceButton())

@bot.tree.command(name="lancio", description="Gioca a testa o croce", guild=discord.Object(id=GUILD_ID))
async def lancio(interaction: Interaction):
    view = TestaCroceView()
    await interaction.response.send_message("🪙 Scegli Testa o Croce!", view=view, ephemeral=True)

async def handle_lancio(interaction, scelta_utente, view):
    last_used = user_lancio_cd.get(interaction.user.id, 0)
    if time.time() - last_used < 15:
        await interaction.response.send_message("⏳ Riprova tra pochi secondi.", ephemeral=True)
        return
    user_lancio_cd[interaction.user.id] = time.time()
    risultato = random.choice(["Testa", "Croce"])
    for item in view.children:
        item.disabled = True
    await interaction.response.edit_message(
        content=f"🪙 È uscito **{risultato}**\n{'Hai vinto!' if scelta_utente == risultato else 'Hai perso!'}",
        view=view
    )

# ========================
# /COUNTING
# ========================
@bot.tree.command(name="setcounting", description="Imposta il canale per il gioco", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def setcounting(interaction: Interaction):
    guild_id = str(interaction.guild.id)
    data["counting"][guild_id] = {
        "channel_id": interaction.channel.id,
        "last_number": 0,
        "last_user_id": None
    }
    await save_data(data)
    await interaction.response.send_message(f"✅ Canale counting impostato su {interaction.channel.mention} e salvato!", ephemeral=True)

@bot.tree.command(name="resetcounting", description="Azzera il conteggio del gioco", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def resetcounting(interaction: Interaction):
    guild_id = str(interaction.guild.id)
    if guild_id not in data.get("counting", {}):
        await interaction.response.send_message("❌ Nessun canale di counting impostato.", ephemeral=True)
        return
    data["counting"][guild_id]["last_number"] = 0
    data["counting"][guild_id]["last_user_id"] = None
    await save_data(data)
    await interaction.response.send_message("🔁 Conteggio resettato a 0.", ephemeral=True)

async def update_counting(message):
    guild_id = str(message.guild.id)
    async with counting_lock:
        if guild_id not in data.get("counting", {}):
            return False
        config = data["counting"][guild_id]
        if message.channel.id != config["channel_id"]:
            return False
        try:
            numero = int(message.content.strip())
        except ValueError:
            return False
        if numero != config["last_number"] + 1:
            config["last_number"] = 0
            config["last_user_id"] = None
            await message.channel.send(f"❌ {message.author.mention} hai sbagliato. Si riparte da 0.")
        elif message.author.id == config["last_user_id"]:
            config["last_number"] = 0
            config["last_user_id"] = None
            await message.channel.send(f"🚫 {message.author.mention} non puoi contare due volte di fila.")
        else:
            config["last_number"] = numero
            config["last_user_id"] = message.author.id
            await message.add_reaction("✅")
        await save_data(data)
        return True

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.guild:
        await update_counting(message)
    await bot.process_commands(message)

# ========================
# STATISTICHE VOCALI
# ========================
@bot.tree.command(name="startstats", description="Avvia i canali vocali per le statistiche", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def slash_startstats(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await avvia_statistiche(interaction)

@bot.tree.command(name="stopstats", description="Ferma i canali vocali per le statistiche", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def slash_stopstats(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await ferma_statistiche(interaction)

@bot.tree.command(name="forzastats", description="Aggiorna manualmente le statistiche", guild=Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def slash_forzastats(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await aggiorna_statistiche(interaction.guild, force=True)
    await interaction.followup.send("🔁 Statistiche aggiornate manualmente.", ephemeral=True)

async def avvia_statistiche(interaction: Interaction):
    global task_attivo
    guild = interaction.guild
    categoria = guild.get_channel(CATEGORY_STATS_ID)
    if not categoria or not isinstance(categoria, discord.CategoryChannel):
        await interaction.followup.send("❌ Categoria non valida. Verifica l'ID.", ephemeral=True)
        return
    async with stats_lock:
        membri_channel = next((ch for ch in categoria.voice_channels if ch.name.startswith("👥 Tot membri")), None)
        bot_channel = next((ch for ch in categoria.voice_channels if ch.name.startswith("🤖 Tot bot")), None)
        if not membri_channel:
            await api_limiter.wait_if_needed()
            membri_channel = await guild.create_voice_channel("👥 Tot membri: ...", category=categoria)
        if not bot_channel:
            await api_limiter.wait_if_needed()
            bot_channel = await guild.create_voice_channel("🤖 Tot bot: ...", category=categoria)
        data["stats"][str(guild.id)] = {
            "membri_id": membri_channel.id,
            "bot_id": bot_channel.id
        }
        await save_data(data)
    if not update_stats.is_running():
        update_stats.start()
    task_attivo = True
    await aggiorna_statistiche(guild, force=True)
    await interaction.followup.send("✅ Statistiche vocali avviate!", ephemeral=True)

async def ferma_statistiche(interaction: Interaction):
    global task_attivo
    if not task_attivo:
        await interaction.followup.send("ℹ️ Statistiche non attive.", ephemeral=True)
        return
    update_stats.stop()
    task_attivo = False
    async with stats_lock:
        data["stats"].pop(str(interaction.guild.id), None)
        await save_data(data)
    await interaction.followup.send("🛑 Statistiche vocali fermate.", ephemeral=True)

@tasks.loop(seconds=300)
async def update_stats():
    for guild_id in list(data.get("stats", {})):
        guild = bot.get_guild(int(guild_id))
        if guild:
            try:
                await aggiorna_statistiche(guild)
                await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ Errore aggiornando {guild.name}: {e}")

async def aggiorna_statistiche(guild, force=False):
    async with stats_lock:
        if str(guild.id) not in data.get("stats", {}):
            return
        stat_data = data["stats"][str(guild.id)]
        membri_channel = guild.get_channel(stat_data.get("membri_id"))
        bot_channel = guild.get_channel(stat_data.get("bot_id"))
        categoria = guild.get_channel(CATEGORY_STATS_ID)
        if not categoria or not isinstance(categoria, discord.CategoryChannel):
            return
        totale_membri = sum(1 for m in guild.members if not m.bot)
        totale_bot = sum(1 for m in guild.members if m.bot)
        if not membri_channel:
            await api_limiter.wait_if_needed()
            membri_channel = await guild.create_voice_channel(f"👥 Tot membri: {totale_membri}", category=categoria)
            data["stats"][str(guild.id)]["membri_id"] = membri_channel.id
        if not bot_channel:
            await api_limiter.wait_if_needed()
            bot_channel = await guild.create_voice_channel(f"🤖 Tot bot: {totale_bot}", category=categoria)
            data["stats"][str(guild.id)]["bot_id"] = bot_channel.id
        new_name_membri = f"👥 Tot membri: {totale_membri}"
        new_name_bot = f"🤖 Tot bot: {totale_bot}"
        try:
            if membri_channel.name != new_name_membri or force:
                await api_limiter.wait_if_needed()
                await membri_channel.edit(name=new_name_membri)
            if bot_channel.name != new_name_bot or force:
                await api_limiter.wait_if_needed()
                await bot_channel.edit(name=new_name_bot)
        except (discord.NotFound, discord.Forbidden):
            pass
        await save_data(data)

async def pulisci_canali_stats(guild):
    categoria = guild.get_channel(CATEGORY_STATS_ID)
    if not categoria:
        return
    for ch in categoria.voice_channels:
        if ch.name.startswith("👥 Tot membri") or ch.name.startswith("🤖 Tot bot"):
            try:
                await ch.delete()
            except Exception:
                pass

# ========================
# /MEME
# ========================
async def get_reddit():
    reddit = asyncpraw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT", "DiscordBot/1.0")
    )
    reddit.read_only = True
    return reddit

@bot.tree.command(name="meme", description="Mostra un meme divertente", guild=Object(id=GUILD_ID))
async def meme(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = time.time()
    cooldown_time = 30
    last_used = user_cooldowns.get(user_id, 0)
    elapsed = now - last_used
    if elapsed < cooldown_time:
        await interaction.response.send_message(f"⏳ Riprova tra **{int(cooldown_time - elapsed)} secondi**.", ephemeral=True)
        return
    user_cooldowns[user_id] = now
    await interaction.response.defer(ephemeral=False)
    reddit = await get_reddit()
    try:
        subreddit = await reddit.subreddit(os.getenv("MEME_SUBREDDIT", "memes"))
        posts = []
        async for post in subreddit.hot(limit=50):
            if post.is_self or post.stickied:
                continue
            posts.append(post)
        if not posts:
            await interaction.followup.send("❌ Nessun meme trovato. Riprova più tardi!")
            return
        post = random.choice(posts)
        url = post.url
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
        if url.lower().endswith(image_extensions):
            embed = Embed(title=post.title, description=f"[Vai al post]({post.shortlink})", color=discord.Color.orange())
            embed.set_image(url=url)
            embed.set_footer(text=f"rPid: {post.id} | Upvotes: {post.score}")
            await interaction.followup.send(embed=embed)
        else:
            if "v.redd.it" in url or "imgur.com" in url:
                await interaction.followup.send(f"🎥 [Guarda il meme qui]({url})")
            else:
                fallback_post = next((p for p in posts if p.url.lower().endswith(image_extensions)), None)
                if fallback_post:
                    embed = Embed(title=fallback_post.title, description=f"[Vai al post]({fallback_post.shortlink})", color=discord.Color.orange())
                    embed.set_image(url=fallback_post.url)
                    embed.set_footer(text=f"rPid: {fallback_post.id} | Upvotes: {fallback_post.score}")
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send("❌ Nessun meme valido trovato. Riprova!")
    except Exception as e:
        await interaction.followup.send(f"❌ Errore nel caricamento del meme: `{str(e)}`")
    finally:
        await reddit.close()

# ========================
# LOG REACTION ROLE
# ========================
async def send_log(member, role, added):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except discord.HTTPException:
            return
    title = "Ruolo aggiunto" if added else "Ruolo Rimosso"
    color = discord.Color.green() if added else discord.Color.red()
    embed = discord.Embed(
        title=title,
        description=f"Utente: {member.mention}\nRuolo: {role.mention}",
        color=color
    )
    embed.set_footer(text=f"Lo Staff • {log_footer()}")
    await channel.send(embed=embed)

# ========================
# /REACTIONROLES
# ========================
@bot.tree.command(
    name="reactionrole", description="Configura l'assegnazione di ruoli tramite reazione su un messaggio", guild=Object(id=GUILD_ID))
@app_commands.describe(
    message_id="ID del messaggio",
    emoji="Emoji da utilizzare (es. :white_check_mark:)",
    role_id="ID dei ruoli separati da virgola (es. 1224..., 1224...)"
)
async def reactionrole(
    interaction: discord.Interaction,
    message_id: str,
    emoji: str,
    role_id: str
):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Non sei autorizzato a usare questo comando.", ephemeral=True)
        return
    if interaction.guild is None:
        await interaction.response.send_message("❌ Usa questo comando in un server.", ephemeral=True)
        return
    if not message_id.isdigit():
        await interaction.response.send_message("❌ L'ID del messaggio deve essere numerico.", ephemeral=True)
        return
    raw_ids = re.split(r'[\s,]+', role_id.strip())
    parsed_ids = [int(rid) for rid in raw_ids if rid.isdigit()]
    if not parsed_ids:
        await interaction.response.send_message("❌ Nessun ID ruolo valido fornito.", ephemeral=True)
        return
    message_id_int = int(message_id)
    valid_roles = []
    for rid in parsed_ids:
        role = interaction.guild.get_role(rid)
        if role is None:
            await interaction.response.send_message(f"❌ Ruolo con ID `{rid}` non trovato nel server.", ephemeral=True)
            return
        valid_roles.append(role)
    channel = interaction.guild.get_channel(interaction.channel_id)
    if channel is None:
        await interaction.response.send_message("❌ Canale non trovato.", ephemeral=True)
        return
    try:
        message = await channel.fetch_message(message_id_int)
    except discord.NotFound:
        await interaction.response.send_message("❌ Messaggio non trovato in questo canale.", ephemeral=True)
        return
    except discord.HTTPException:
        await interaction.response.send_message("❌ Errore nel recupero del messaggio.", ephemeral=True)
        return
    for item in data.get("reaction_roles", []):
        if (item["message_id"] == message_id_int and item["emoji"] == emoji and item["guild_id"] == interaction.guild_id):
            await interaction.response.send_message(
                "❌ Reaction Role già configurato per questa emoji su questo messaggio.\n"
                "Usa prima `/removereactionrole` per rimuoverlo e poi riconfiguralo.",
                ephemeral=True
            )
            return
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Emoji non valida o non disponibile.", ephemeral=True)
        return
    data["reaction_roles"].append({
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "message_id": message_id_int,
        "emoji": emoji,
        "role_ids": parsed_ids
    })
    await save_data(data)
    ruoli_text = ", ".join([r.mention for r in valid_roles])
    await interaction.response.send_message(
        f"✅ Reaction Role configurato!\n\n"
        f"**Messaggio:** `{message_id}`\n"
        f"**Emoji:** {emoji}\n"
        f"**Ruoli assegnati:** {ruoli_text}",
        ephemeral=True
    )

# ========================
# /REMOVEREACTIONROLES
# ========================
@bot.tree.command(name="removereactionrole", description="Rimuove l'assegnazione di ruoli tramite reazione da un messaggio", guild=Object(id=GUILD_ID))
@app_commands.describe(message_id="ID del messaggio", emoji="Emoji configurata")
async def removereactionrole(
    interaction: discord.Interaction,
    message_id: str,
    emoji: str
):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Non sei autorizzato a usare questo comando.", ephemeral=True)
        return
    if interaction.guild is None:
        await interaction.response.send_message("❌ Usa questo comando in un server.", ephemeral=True)
        return
    if not message_id.isdigit():
        await interaction.response.send_message("❌ ID messaggio non valido.", ephemeral=True)
        return
    message_id_int = int(message_id)
    old_length = len(data.get("reaction_roles", []))
    data["reaction_roles"] = [
        item for item in data.get("reaction_roles", [])
        if not (item["message_id"] == message_id_int and item["emoji"] == emoji and item["guild_id"] == interaction.guild_id)
    ]
    if len(data["reaction_roles"]) == old_length:
        await interaction.response.send_message("❌ Ruolo Reazione non trovato.", ephemeral=True)
        return
    await save_data(data)
    await interaction.response.send_message("✅ Ruolo Reazione rimosso correttamente.", ephemeral=True)

# ========================
# GESTIONE REAZIONI
# ========================
async def handle_reaction(payload, added):
    if bot.user is None or payload.user_id == bot.user.id or payload.guild_id is None:
        return
    for item in data.get("reaction_roles", []):
        if item["message_id"] != payload.message_id or item["guild_id"] != payload.guild_id or item["emoji"] != str(payload.emoji):
            continue
        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            continue
        try:
            member = await guild.fetch_member(payload.user_id)
        except (discord.NotFound, discord.HTTPException):
            continue
        role_ids = item.get("role_ids")
        if role_ids is None:
            role_ids = [item.get("role_id")] if item.get("role_id") else []
        for rid in role_ids:
            role = guild.get_role(rid)
            if role is None:
                continue
            try:
                if added:
                    if role not in member.roles:
                        await member.add_roles(role, reason="Reaction Role")
                        await send_log(member, role, True)
                else:
                    if role in member.roles:
                        await member.remove_roles(role, reason="Reaction Role")
                        await send_log(member, role, False)
            except discord.Forbidden:
                print(f"Permessi insufficienti per assegnare il ruolo: {role.name}")
            except discord.HTTPException as error:
                print(f"Errore Discord per il ruolo {role.name}: {error}")

# ========================
# GESTORE ERRORI COMANDI SLASH
# ========================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    import traceback
    print(f"\n{'='*60}")
    print(f"❌ ERRORE nel comando '/{interaction.command.name}'")
    print(f"Utente: {interaction.user.name} ({interaction.user.id})")
    print(f"Server: {interaction.guild.name if interaction.guild else 'DM'}")
    print(f"{'='*60}")
    traceback.print_exc()
    print(f"{'='*60}\n")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ Errore durante l'esecuzione del comando.\n"
                f"Dettagli: `{error}`\n"
                f"Controlla il terminale del bot per informazioni dettagliate.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ Errore: `{error}`",
                ephemeral=True
            )
    except Exception as e:
        print(f"❌ Impossibile inviare messaggio di errore: {e}")

# ========================
# ON READY STABILE
# ========================
@bot.event
async def on_ready():
    print(f"✅ Bot online come {bot.user}")
    bot.add_view(TicketPanelView())
    await setup_ticket_panel()
    try:
        synced = await bot.tree.sync(guild=Object(id=GUILD_ID))
        print(f"✅ Comandi sincronizzati: {len(synced)}")
    except Exception as e:
        print(f"❌ Errore sync: {e}")
    print(f"Ruoli Reazione caricati: {len(data.get('reaction_roles', []))}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="la community"))
    if data.get("stats") and not update_stats.is_running():
        update_stats.start()

# ========================
# AVVIO BOT
# ========================
async def main():
    await init()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot arrestato correttamente.")
    except asyncio.CancelledError:
        print("Arresto del bot completato.")