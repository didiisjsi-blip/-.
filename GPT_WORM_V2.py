import requests
import discord
from discord.ext import commands
from discord.ext import commands, tasks 
import sys
import asyncio
import os
import json
import sqlite3
import aiohttp
from langdetect import detect
from datetime import datetime
from discord import ui
import time

# =========================================================
# 1. GLOBAL CONSTANTS
# =========================================================
# *** โปรดเปลี่ยน DISCORD_TOKEN ***
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


CONFIG_FILE = "wormgpt_configmre.json"
PROMPT_FILE = "system-prompt.txt"

DEFAULT_API_KEY = os.getenv("OPENROUTER_API_KEY")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-2.0-flash-exp:free" 
DEFAULT_LANGUAGE = "Thai"

SITE_URL = "https://github.com/00x0kafyy/worm-ai"
SITE_NAME = "WormGPT Discord Bot"

MAIN_COLOR = 0xFF0000
ERROR_COLOR = discord.Color.red()

# =========================================================
# 2. GUILD MANAGEMENT CONSTANTS (โปรดแก้ไข Webhook URL)
# =========================================================
# *** โปรดเปลี่ยน YOUR_WEBHOOK_URL_HERE เป็น Webhook URL จริงของคุณ ***
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

GUILD_FILE = "guilds.json"
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
# ต้องเปิด Intents 2 ตัวนี้ใน Portal ด้วย
intents.guilds = True 
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if 'auto_reply_channels' in config:
                    del config['auto_reply_channels']
                if 'private_chats' in config:
                    pass 
                return config
        except Exception as e:
            print(f"Error loading config: {e}. Using defaults.", file=sys.stderr)

    config = {
        "api_key": DEFAULT_API_KEY,
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "language": DEFAULT_LANGUAGE,
        "private_chats": {}
    }
    save_config(config)
    return config

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)


DB_FILE = "wormgpt.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # ตารางสำหรับเก็บการตั้งค่าของแต่ละเซิร์ฟเวอร์
    c.execute('''CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id TEXT PRIMARY KEY,
        approval_channel_id TEXT,
        private_chat_category_id TEXT,
        log_channel_id TEXT,
        auto_reply_channels TEXT, -- JSON string
        allowed_role_ids TEXT -- JSON string of role IDs
    )''')
    conn.commit()
    conn.close()

# **ฟังก์ชันอ่านค่าตั้งค่าเฉพาะเซิร์ฟเวอร์**
def get_guild_setting(guild_id: int, key: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f'SELECT {key} FROM guild_settings WHERE guild_id = ?', (str(guild_id),))
    row = c.fetchone()
    conn.close()
    if row and row[0] is not None:
        if key in ['auto_reply_channels', 'allowed_role_ids']:
            try: return json.loads(row[0])
            except: return []
        return row[0]
    
    if key in ['approval_channel_id', 'private_chat_category_id', 'log_channel_id']:
        return "0" 
    
    return [] if key in ['auto_reply_channels', 'allowed_role_ids'] else None

# **ฟังก์ชันตั้งค่าเฉพาะเซิร์ฟเวอร์**
def set_guild_setting(guild_id: int, key: str, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if key in ['auto_reply_channels', 'allowed_role_ids']:
        value_to_save = json.dumps(value)
    else:
        value_to_save = str(value)

    c.execute('SELECT * FROM guild_settings WHERE guild_id = ?', (str(guild_id),))
    if c.fetchone():
        c.execute(f'UPDATE guild_settings SET {key} = ? WHERE guild_id = ?', (value_to_save, str(guild_id)))
    else:
        c.execute(f'INSERT INTO guild_settings (guild_id, {key}) VALUES (?, ?)', (str(guild_id), value_to_save))

    conn.commit()
    conn.close()

def add_auto_reply_channel(guild_id: int, channel_id: int):
    channels = get_guild_setting(guild_id, 'auto_reply_channels')
    if channel_id not in channels:
        channels.append(channel_id)
        set_guild_setting(guild_id, 'auto_reply_channels', channels)

def remove_auto_reply_channel(guild_id: int, channel_id: int):
    channels = get_guild_setting(guild_id, 'auto_reply_channels')
    if channel_id in channels:
        channels.remove(channel_id)
        set_guild_setting(guild_id, 'auto_reply_channels', channels)
        return True
    return False

# =========================================================
# HELPER: ตรวจสอบยศที่ได้รับอนุญาต
# =========================================================
def check_allowed_role(member: discord.Member, guild_id: int) -> bool:
    """ตรวจสอบว่าสมาชิกมีสิทธิ์ในการใช้ฟีเจอร์ที่ถูกจำกัดหรือไม่"""
    allowed_ids = get_guild_setting(guild_id, 'allowed_role_ids')
    
    # ถ้า allowed_ids เป็นรายการว่าง แสดงว่าไม่ได้ตั้งค่า (อนุญาตทุกคน)
    if not allowed_ids:
        return True
        
    member_role_ids = [role.id for role in member.roles]
    
    # ตรวจสอบว่าสมาชิกมียศใดๆ ในรายการ allowed_ids หรือไม่
    return any(role_id in allowed_ids for role_id in member_role_ids)

def format_allowed_roles(guild: discord.Guild, allowed_ids: list) -> str:
    """ฟอร์แมตรายการ Role ID เป็นข้อความที่มนุษย์อ่านได้"""
    if not allowed_ids:
        return "✅ ทุกคนสามารถใช้งานได้ (ไม่มีการจำกัดยศ)"
    
    role_mentions = []
    for r_id in allowed_ids:
        role = guild.get_role(r_id)
        if role:
            role_mentions.append(role.mention)
        else:
            role_mentions.append(f"บทบาทที่ไม่พบ: `{r_id}`")
            
    return "❌ จำกัดเฉพาะยศ:\n" + ", ".join(role_mentions)

# =========================================================
# GUILD MANAGEMENT FUNCTIONS (แก้ไข joined_at)
# =========================================================
def update_guild_file(bot):
    """เขียนรายการเซิร์ฟเวอร์ทั้งหมดที่บอทเข้าร่วมลงในไฟล์ JSON"""
    guild_data = []
    for guild in bot.guilds:
        # FIX: แก้ไขการเข้าถึง joined_at โดยใช้ guild.me.joined_at แทน guild.joined_at
        joined_at = guild.me.joined_at if guild.me else None
        
        guild_data.append({
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "owner_id": str(guild.owner_id),
            "joined_at": joined_at.isoformat() if joined_at else None
        })

    try:
        with open(GUILD_FILE, "w", encoding="utf-8") as f:
            json.dump(guild_data, f, indent=2, ensure_ascii=False)
        print(f"✅ Updated {GUILD_FILE} with {len(guild_data)} guilds.")
    except Exception as e:
        print(f"❌ Error writing guild file: {e}", file=sys.stderr)


# *** แก้ไข: เพิ่ม invite_url ใน Webhook ***
async def send_guild_webhook(guild: discord.Guild, is_join: bool, invite_url: str = None):
    """ส่ง Webhook แจ้งเตือนเมื่อบอทเข้า/ออกจากเซิร์ฟเวอร์"""
    if WEBHOOK_URL == "YOUR_WEBHOOK_URL_HERE":
        print("⚠️ WEBHOOK_URL is not set. Skipping webhook notification.", file=sys.stderr)
        return
        
    action = "✅ เข้าร่วม" if is_join else "❌ ออกจาก"
    color = 0x00FF00 if is_join else 0xFF0000

    embed = {
        "title": f"บอท {action} เซิร์ฟเวอร์ใหม่",
        "description": f"**{action} เซิร์ฟเวอร์:** {guild.name}",
        "color": color,
        "timestamp": datetime.now().isoformat(),
        "fields": [
            {"name": "ID", "value": f"`{guild.id}`", "inline": True},
            {"name": "สมาชิก", "value": f"{guild.member_count}", "inline": True},
            # เพิ่ม Invite Link
            {"name": "ลิงก์เชิญ", "value": f"[คลิกเพื่อเข้าสู่เซิร์ฟเวอร์]({invite_url})" if invite_url and is_join else "N/A", "inline": False},
            {"name": "เจ้าของ (ID)", "value": f"`{guild.owner_id}`", "inline": False},
        ],
        "footer": {"text": f"ปัจจุบันอยู่: {len(bot.guilds)} เซิร์ฟเวอร์"}
    }
    
    payload = {
        "embeds": [embed]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(WEBHOOK_URL, json=payload) as response:
                if response.status not in (200, 204):
                    print(f"❌ Failed to send webhook. Status: {response.status}", file=sys.stderr)
                else:
                    print(f"✅ Webhook sent successfully for {action} {guild.name}")
    except Exception as e:
        print(f"❌ Error sending webhook: {e}", file=sys.stderr)
# =========================================================


def get_jailbreak_prompt():
    if not os.path.exists(PROMPT_FILE):
        default_prompt = "You are WormGPT, an advanced AI assistant. Respond as quickly as possible while maintaining high quality. Be concise but informative. Always respond in the user's language. Provide accurate and helpful answers."
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(default_prompt)
        return default_prompt

    try:
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
            else:
                return "You are WormGPT, an advanced AI assistant. Respond as quickly as possible while maintaining high quality. Be concise but informative. Always respond in the user's language. Provide accurate and helpful answers."
    except Exception as e:
        print(f"Error reading system-prompt: {e}. Using default.", file=sys.stderr)
        return "You are WormGPT, an advanced AI assistant. Respond as quickly as possible while maintaining high quality. Be concise but informative. Always respond in the user's language. Provide accurate and helpful answers."


async def call_api_async(user_input):
    config = load_config()

    try:
        detected_lang = detect(user_input[:500])
        lang_map = {'id':'Indonesian','en':'English','es':'Spanish','ar':'Arabic','th':'Thai','pt':'Portuguese'}
        current_lang = lang_map.get(detected_lang, 'English')
    except:
        current_lang = config["language"]

    try:
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "HTTP-Referer": SITE_URL,
            "X-Title": SITE_NAME,
            "Content-Type": "application/json"
        }

        max_tokens = 8000

        data = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": get_jailbreak_prompt()},
                {"role": "user", "content": user_input}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{config['base_url']}/chat/completions", headers=headers, json=data) as response:
                response.raise_for_status()
                result = await response.json()
                return result['choices'][0]['message']['content']

    except aiohttp.ClientError as e:
        error_message = f"API Request Error: {e}"
        try:
            error_details = await response.json()
            if 'error' in error_details and 'message' in error_details['error']:
                error_message = f"OpenRouter Error: {error_details['error']['message']}"
        except:
            pass
        return f"🤖 **[WormGPT API Error]**: {error_message}"
    except Exception as e:
        return f"🤖 **[WormGPT API Error]**: Unexpected error: {e}"


async def read_text_attachment(
    attachment: discord.Attachment,
    max_size=1_000_000
):
    if attachment.size > max_size:
        return f"[ไฟล์ {attachment.filename} ใหญ่เกินไป]"

    allowed_ext = (
        ".txt", ".md", ".json",
        ".py", ".js", ".html", ".css"
    )

    if not attachment.filename.lower().endswith(allowed_ext):
        return f"[ไม่รองรับไฟล์ {attachment.filename}]"

    try:
        data = await attachment.read()
        return data.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"[อ่านไฟล์ {attachment.filename} ไม่สำเร็จ: {e}]"


async def send_ai_response(channel, question_text, response_text, reply_to_message=None):
    if response_text.startswith("🤖 **[WormGPT API Error]**"):
        error_embed = discord.Embed(
            title="❌ การเรียกใช้ API ผิดพลาด",
            description=response_text,
            color=ERROR_COLOR,
            timestamp=datetime.now()
        )
        if reply_to_message:
            await reply_to_message.reply(embed=error_embed)
        else:
            await channel.send(embed=error_embed)
        return

    MAX_DISCORD_MESSAGE_LENGTH = 2000
    
    if len(response_text) <= MAX_DISCORD_MESSAGE_LENGTH:
        
        response_embed = discord.Embed(
            title="✨ คำตอบจาก WormGPT",
            description=response_text,
            color=MAIN_COLOR,
            timestamp=datetime.now()
        )
        truncated_question = question_text[:500] + ('...' if len(question_text) > 500 else '')
        response_embed.add_field(name="คำถามต้นฉบับ", value=f"```\n{truncated_question}\n```", inline=False)
        response_embed.set_footer(text="WormGPT | ตอบกลับสั้น")

        if reply_to_message:
            await reply_to_message.reply(embed=response_embed)
        else:
            await channel.send(embed=response_embed)
        
    else:
        
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"WormGPT_Response_{timestamp_str}.txt"
        file_path = os.path.join(os.getcwd(), filename)

        try:
            file_content = (
                f"--- คำถามต้นฉบับ ---\n"
                f"{question_text}\n\n"
                f"--- คำตอบจาก WormGPT ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---\n"
                f"{response_text}"
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(file_content)

            file = discord.File(file_path, filename=filename)

            file_embed = discord.Embed(
                title="📄 คำตอบถูกส่งเป็นไฟล์ข้อความ (ข้อความยาว)",
                description=f"✅ คำตอบสำหรับคำถามของคุณมีความยาวเกิน 2000 ตัวอักษร จึงถูกสร้างเป็นไฟล์ `{filename}`",
                color=MAIN_COLOR,
                timestamp=datetime.now()
            )
            truncated_question = question_text[:500] + ('...' if len(question_text) > 500 else '')
            file_embed.add_field(name="คำถามต้นฉบับ", value=f"```\n{truncated_question}\n```", inline=False)
            file_embed.set_footer(text="WormGPT | สร้างไฟล์ TXT เพื่อเลี่ยงข้อจำกัดของข้อความยาว")

            if reply_to_message:
                await reply_to_message.reply(embed=file_embed, file=file)
            else:
                await channel.send(embed=file_embed, file=file)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ ข้อผิดพลาดในการจัดการไฟล์",
                description=f"ไม่สามารถสร้างหรือส่งไฟล์ `.txt` ได้: {e}",
                color=ERROR_COLOR
            )
            await channel.send(embed=error_embed)
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

class ConfirmView(ui.View):
    def __init__(self, bot, channel_to_add: discord.TextChannel, original_author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.channel_to_add = channel_to_add
        self.original_author_id = original_author_id
        self.guild_id = channel_to_add.guild.id

    @ui.button(label="✅ ยืนยันการเปิดใช้งาน", style=discord.ButtonStyle.success, custom_id="confirm_add")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild.id != self.guild_id:
            await interaction.response.send_message("❌ การกระทำนี้ต้องทำในเซิร์ฟเวอร์เดิม", ephemeral=True)
            return
            
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Manage Channels`", ephemeral=True)
            return

        channels = get_guild_setting(self.guild_id, 'auto_reply_channels')
        channel_id = self.channel_to_add.id

        if channel_id in channels:
            await interaction.response.send_message(
                f"⚠️ {self.channel_to_add.mention} เปิดใช้งานอยู่แล้ว", ephemeral=True
            )
            return

        add_auto_reply_channel(self.guild_id, channel_id)

        await interaction.response.send_message(
            f"✅ เปิดใช้งาน WormGPT Auto-Reply ใน {self.channel_to_add.mention} สำเร็จ!", ephemeral=True
        )

        original_user = self.bot.get_user(self.original_author_id)
        if original_user:
            try:
                await original_user.send(
                    f"🎉 คำขอของคุณได้รับการอนุมัติแล้ว! WormGPT จะตอบทุกข้อความใน {self.channel_to_add.mention} โดยอัตโนมัติ"
                )
            except:
                pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    @ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger, custom_id="cancel_add")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Manage Channels`", ephemeral=True)
            return
        
        await interaction.response.send_message("❌ ยกเลิกการเปิดใช้งาน", ephemeral=True)

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

class PrivateChatView(ui.View):
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.add_item(discord.ui.Button(label="Discord", style=discord.ButtonStyle.secondary, url="https://discord.gg/k2BerbWpbe", emoji="<a:discord_loading:1454254193974968484>"))
        # ปุ่ม "🎁 รับฟรี 2 วัน" ถูกลบออกไปแล้วในโค้ดนี้ ตามคำขอ

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์นี้เท่านั้น", ephemeral=True)
            return False
            
        user_id_str = str(interaction.user.id)
        config = load_config() 
        private_chats = config.get('private_chats', {})

        if user_id_str in private_chats:
            channel_id = private_chats[user_id_str]
            channel = self.bot.get_channel(channel_id)
            
            if channel and channel.guild and channel.guild.id == self.guild_id:
                await interaction.response.send_message(
                    f"⚠️ คุณมีห้องส่วนตัวอยู่แล้ว: {channel.mention}\n"
                    f"หากต้องการสร้างห้องใหม่ กรุณาใช้คำสั่ง **/delete_private_chat** เพื่อลบห้องเดิมก่อน", 
                    ephemeral=True
                )
                return False 
            elif channel and channel.guild and channel.guild.id != self.guild_id:
                await interaction.response.send_message(
                    f"⚠️ คุณมีห้องส่วนตัวอยู่แล้วในเซิร์ฟเวอร์อื่น: {channel.guild.name}\n"
                    f"ไม่อนุญาตให้สร้างมากกว่า 1 ห้อง",
                    ephemeral=True
                )
                return False
            else:
                # Cleanup logic
                del config['private_chats'][user_id_str]
                save_config(config)
        
        return True 

    @ui.button(label="🤖กดเพื่อสร้างห้องส่วนตัว", style=discord.ButtonStyle.primary, custom_id="create_private_chat")
    async def create_private_chat_button(self, interaction: discord.Interaction, button: ui.Button):
        user = interaction.user
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message("❌ ต้องใช้คำสั่งนี้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
            return
        
        category_id_str = get_guild_setting(guild.id, 'private_chat_category_id')
        if category_id_str == "0":
            await interaction.response.send_message(
                f"❌ ผู้ดูแลระบบยังไม่ได้ตั้งค่า Category สำหรับห้องส่วนตัว กรุณาใช้คำสั่ง **/set_id private_category <Category Channel ID>**", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # ตรวจสอบยศที่ได้รับอนุญาต
        if not check_allowed_role(user, guild.id):
            allowed_ids = get_guild_setting(guild.id, 'allowed_role_ids')
            role_list_str = format_allowed_roles(guild, allowed_ids)
            await interaction.followup.send(
                f"❌ คุณไม่มีสิทธิ์ในการสร้างห้องส่วนตัว\n\n**ข้อกำหนด:**\n{role_list_str.replace('❌ จำกัดเฉพาะยศ:', 'คุณต้องมียศใดยศหนึ่งดังนี้:')}", 
                ephemeral=True
            )
            return
        
        try:
            channel_name = f"🤖-chat-{user.name.lower().replace(' ', '-')[:15]}"

            category = guild.get_channel(int(category_id_str))
            if not category or not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send(
                    f"❌ ไม่พบ Category ID: `{category_id_str}` กรุณาตรวจสอบการตั้งค่าด้วยคำสั่ง **/set_id**", ephemeral=True
                )
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            new_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"ห้อง WormGPT ส่วนตัวของ {user.display_name} | ID: {user.id}"
            )

            config = load_config()
            config.setdefault('private_chats', {})[str(user.id)] = new_channel.id
            save_config(config)

            await interaction.followup.send(
                f"✅ สร้างห้องส่วนตัวสำเร็จ! ไปที่ {new_channel.mention} เพื่อเริ่มสนทนา", ephemeral=True
            )
            
            welcome_embed = discord.Embed(
                title="ยินดีต้อนรับสู่ห้องส่วนตัว WormGPT",
                description="✅ ห้องนี้ถูกสร้างขึ้นมาเพื่อคุณโดยเฉพาะ ทุกข้อความที่คุณพิมพ์จะถูกตอบกลับโดย AI โดยอัตโนมัติ\n\n**เริ่มพิมพ์คำถามได้เลย!**",
                color=MAIN_COLOR
            )
            await new_channel.send(user.mention, embed=welcome_embed)

        except discord.Forbidden:
            await interaction.followup.send("❌ บอทไม่มีสิทธิ์สร้างห้องสนทนาในเซิร์ฟเวอร์นี้ (Forbidden)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", ephemeral=True)

# =========================================================================================
# FIX: แก้ไข Type Hint ของ 'action' เป็น str เพื่อแก้ปัญหา Autocomplete TypeError
# =========================================================================================
@tree.command(name="manage_private_roles", description="[ADMIN] จัดการยศที่ได้รับอนุญาตให้ใช้ฟีเจอร์ Private Chat")
@commands.has_permissions(administrator=True)
async def manage_private_roles_command(
    interaction: discord.Interaction,
    action: str, # <--- แก้ไขที่นี่
    role: discord.Role = None 
):
    guild_id = interaction.guild_id
    guild = interaction.guild
    if not guild or not guild_id:
        await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    current_roles = get_guild_setting(guild_id, 'allowed_role_ids')
    action_type = action
    
    if action_type == 'clear':
        set_guild_setting(guild_id, 'allowed_role_ids', [])
        message = "✅ ล้างรายการยศที่ได้รับอนุญาตแล้ว: **ตอนนี้ทุกคนสามารถใช้ Private Chat ได้**"
    
    elif action_type == 'add':
        if not role:
            await interaction.followup.send("❌ ต้องระบุยศที่ต้องการเพิ่ม", ephemeral=True)
            return
            
        role_id = role.id
        if role_id not in current_roles:
            current_roles.append(role_id)
            set_guild_setting(guild_id, 'allowed_role_ids', current_roles)
            message = f"✅ เพิ่มยศ {role.mention} เข้าในรายการอนุญาตแล้ว"
        else:
            message = f"⚠️ ยศ {role.mention} อยู่ในรายการอนุญาตอยู่แล้ว"
            
    elif action_type == 'remove':
        if not role:
            await interaction.followup.send("❌ ต้องระบุยศที่ต้องการลบ", ephemeral=True)
            return
            
        role_id = role.id
        if role_id in current_roles:
            current_roles.remove(role_id)
            set_guild_setting(guild_id, 'allowed_role_ids', current_roles)
            message = f"✅ ลบยศ {role.mention} ออกจากรายการอนุญาตแล้ว"
        else:
            message = f"⚠️ ยศ {role.mention} ไม่อยู่ในรายการอนุญาต"

    elif action_type == 'list':
        message = f"ℹ️ สถานะปัจจุบันของยศที่ได้รับอนุญาตให้ใช้ Private Chat:\n{format_allowed_roles(guild, current_roles)}"
        await interaction.followup.send(message, ephemeral=True)
        return
        
    else:
        await interaction.followup.send("❌ คำสั่งไม่ถูกต้อง", ephemeral=True)
        return

    current_roles_after_action = get_guild_setting(guild_id, 'allowed_role_ids')
    final_status = format_allowed_roles(guild, current_roles_after_action)

    embed = discord.Embed(
        title=f"จัดการสิทธิ์ Private Chat: {action_type.upper()}",
        description=f"{message}\n\n**สถานะปัจจุบัน:**\n{final_status}",
        color=MAIN_COLOR
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@manage_private_roles_command.autocomplete('action')
async def manage_roles_autocomplete(interaction: discord.Interaction, current: str):
    choices = [
        discord.app_commands.Choice(name="เพิ่มยศ (add)", value='add'),
        discord.app_commands.Choice(name="ลบยศ (remove)", value='remove'),
        discord.app_commands.Choice(name="ล้างรายการทั้งหมด (clear)", value='clear'),
        discord.app_commands.Choice(name="ดูรายการปัจจุบัน (list)", value='list'),
    ]
    return [
        choice for choice in choices if current.lower() in choice.name.lower()
    ]


@manage_private_roles_command.error
async def manage_private_roles_error(interaction: discord.Interaction, error):
    if isinstance(error, commands.MissingPermissions):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Administrator` ในการใช้คำสั่งนี้", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {error}", ephemeral=True)
# =========================================================================================

# =========================================================================================
# FIX: แก้ไข Type Hint ของ 'ประเภท' เป็น str เพื่อแก้ปัญหา Autocomplete TypeError
# =========================================================================================
@tree.command(name="set_id", description="[ADMIN] ตั้งค่า Channel ID และ Category ID ที่จำเป็นสำหรับ WormGPT")
@commands.has_permissions(administrator=True)
async def set_id_command(
    interaction: discord.Interaction,
    ประเภท: str, # <--- แก้ไขที่นี่
    ไอดี: str
):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        return
        
    key = ประเภท
    
    try:
        id_value = int(ไอดี)
    except ValueError:
        await interaction.response.send_message(f"❌ ID ที่ระบุต้องเป็นตัวเลข", ephemeral=True)
        return

    set_guild_setting(guild_id, key, id_value)
    
    approval_id = get_guild_setting(guild_id, 'approval_channel_id')
    private_cat_id = get_guild_setting(guild_id, 'private_chat_category_id')
    log_id = get_guild_setting(guild_id, 'log_channel_id')
    
    embed = discord.Embed(
        title="✅ ตั้งค่า Channel ID สำเร็จ",
        description=f"ตั้งค่า `{key}` เป็น `{id_value}` เรียบร้อยแล้ว\n\n**สถานะการตั้งค่าปัจจุบันของเซิร์ฟเวอร์:**",
        color=MAIN_COLOR
    )
    
    embed.add_field(
        name="1. 📢 Channel อนุมัติ (Approval Channel)",
        value=f"ID: `{approval_id}`\nสถานะ: {'✅ พร้อมใช้งาน' if approval_id != '0' else '❌ ยังไม่ตั้งค่า'}",
        inline=False
    )
    embed.add_field(
        name="2. 📂 Category ห้องส่วนตัว (Private Category)",
        value=f"ID: `{private_cat_id}`\nสถานะ: {'✅ พร้อมใช้งาน' if private_cat_id != '0' else '❌ ยังไม่ตั้งค่า'}",
        inline=False
    )
    embed.add_field(
        name="3. 📝 Channel Log (Log Channel)",
        value=f"ID: `{log_id}`\nสถานะ: {'✅ พร้อมใช้งาน' if log_id != '0' else '❌ ยังไม่ตั้งค่า'}",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@set_id_command.autocomplete('ประเภท')
async def set_id_autocomplete(interaction: discord.Interaction, current: str):
    choices = [
        discord.app_commands.Choice(name="Approval Channel ID", value='approval_channel_id'),
        discord.app_commands.Choice(name="Private Chat Category ID", value='private_chat_category_id'),
        discord.app_commands.Choice(name="Log Channel ID", value='log_channel_id')
    ]
    return [
        choice for choice in choices if current.lower() in choice.name.lower()
    ]


@set_id_command.error
async def set_id_error(interaction: discord.Interaction, error):
    if isinstance(error, commands.MissingPermissions):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Administrator` ในการใช้คำสั่งนี้", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {error}", ephemeral=True)


@tree.command(name="setup_private_chat", description="[ADMIN] ส่งเมนูสำหรับสร้างห้องส่วนตัวไปยัง Channel ที่ต้องการ")
@commands.has_permissions(administrator=True)
async def setup_private_chat_command(
    interaction: discord.Interaction,
    ช่องสำหรับเมนู: discord.TextChannel
):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        return
        
    private_cat_id = get_guild_setting(guild_id, 'private_chat_category_id')

    if private_cat_id == "0":
         await interaction.response.send_message(
            "❌ กรุณาตั้งค่า `Private Chat Category ID` ก่อน โดยใช้คำสั่ง **/set_id private_category <ID>**", ephemeral=True
        )
         return
    
    await interaction.response.send_message(
        f"✅ กำลังส่งเมนูไปยัง {ช่องสำหรับเมนู.mention}", ephemeral=True
    )
    
    current_roles = get_guild_setting(guild_id, 'allowed_role_ids')
    role_status_text = format_allowed_roles(interaction.guild, current_roles)
    
    embed = discord.Embed(
        title="✨ สร้างห้องแชท WormGPT ส่วนตัว| Nexus HUB",
        description=f"กดปุ่มด้านล่างเพื่อสร้าง Channel แชทส่วนตัวกับ WormGPT\n"
                    f"จะไม่มีใครมองเห็นห้องนี้นอกจากคุณ\n"
                    f"สามารถสร้างได้เพียง1ห้องต่อ1ผู้ใช้เท่านั้น\n\n"
                    f"**ℹ️ สถานะการอนุญาต:** {role_status_text.replace('❌ จำกัดเฉพาะยศ:', 'จำกัดเฉพาะยศ:')}",
        color=0xFF0000,
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url='https://img5.pic.in.th/file/secure-sv1/discord_fake_avatar_decorations_1767147632128.gif') #โลโก้
    embed.set_image(url='https://img5.pic.in.th/file/secure-sv1/standard-5c281df69c69d8f20.gif') #แบนเนอร์
    embed.set_footer(text="ห้องส่วนตัวจะอยู่ด้านล่างของหมวดหมนู่นี้ | Nexus HUB")
    
    view = PrivateChatView(bot=bot, guild_id=guild_id)
    await ช่องสำหรับเมนู.send(embed=embed, view=view)


@setup_private_chat_command.error
async def setup_private_chat_error(interaction: discord.Interaction, error):
    if isinstance(error, commands.MissingPermissions):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ `Administrator` ในการใช้คำสั่งนี้", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {error}", ephemeral=True)

# =========================================================
# NEW: TASK สำหรับอัปเดตสถานะของบอท
# =========================================================
@tasks.loop(minutes=1.0)
async def update_status_task():
    """อัปเดตสถานะของบอทให้แสดงจำนวนเซิร์ฟเวอร์ทุก 1 นาที"""
    await bot.wait_until_ready()
    
    server_count = len(bot.guilds)
    status_message = f"✅ : Already joined {server_count} server"
    
    try:
        # ใช้ discord.Game เพื่อแสดงสถานะ "Playing"
        await bot.change_presence(activity=discord.Game(name=status_message))
        print(f"🤖 Status updated: {status_message}")
    except Exception as e:
        print(f"❌ Failed to update bot status: {e}", file=sys.stderr)

# =========================================================

@bot.event
async def on_ready():
    print(f'🤖 WormGPT Ready — Logged in as {bot.user}')

    try:
        synced = await tree.sync()
        print(f"Commands synced: {len(synced)}")
    except Exception as e:
        print(f"Slash sync failed: {e}", file=sys.stderr)

    config = load_config()
    print(f"Model: {config['model']}")

    init_db()
    
    # อัปเดตไฟล์รายชื่อเซิร์ฟเวอร์
    update_guild_file(bot)
    
    # NEW: เริ่มต้น Task สำหรับอัปเดตสถานะ
    if not update_status_task.is_running():
        update_status_task.start()

# =========================================================
# GUILD JOIN/LEAVE EVENTS (มีการแก้ไขส่วนนี้เพื่อสร้าง Invite Link)
# =========================================================
@bot.event
async def on_guild_join(guild: discord.Guild):
    print(f"🎉 Joined new guild: {guild.name} ({guild.id})")
    update_guild_file(bot)
    
    # NEW: อัปเดตสถานะทันทีเมื่อเข้าเซิร์ฟเวอร์ใหม่
    server_count = len(bot.guilds)
    await bot.change_presence(activity=discord.Game(name=f"✅ : Already joined {server_count} server"))
    
    invite_link = None
    
    # พยายามสร้างลิงก์เชิญถาวร
    for channel in guild.text_channels:
        try:
            # สร้างลิงก์เชิญ (ไม่หมดอายุ, ไม่จำกัดการใช้งาน) ใน Channel แรกที่บอทมีสิทธิ์
            invite = await channel.create_invite(max_age=0, max_uses=0, temporary=False)
            invite_link = invite.url
            print(f"🔗 Created invite link: {invite_link} in #{channel.name}")
            break # หยุดเมื่อสร้างลิงก์ได้แล้ว
        except discord.Forbidden:
            # บอทไม่มีสิทธิ์สร้างลิงก์ใน Channel นี้ ไป Channel ต่อไป
            continue
        except Exception as e:
            print(f"❌ Error creating invite in #{channel.name}: {e}", file=sys.stderr)
    
    await send_guild_webhook(guild, is_join=True, invite_url=invite_link)

@bot.event
async def on_guild_remove(guild: discord.Guild):
    print(f"👋 Left guild: {guild.name} ({guild.id})")
    update_guild_file(bot)
    
    # NEW: อัปเดตสถานะทันทีเมื่อออกจากเซิร์ฟเวอร์
    server_count = len(bot.guilds)
    await bot.change_presence(activity=discord.Game(name=f"✅ : Already joined {server_count} server"))
    
    await send_guild_webhook(guild, is_join=False) # ไม่ต้องส่ง Invite URL เมื่อออก
# =========================================================
    
@bot.event
async def on_message(message):
    await bot.process_commands(message) # ตรวจสอบคำสั่ง Prefix (เช่น !) ก่อน

    if message.author.bot:
        return

    channel = message.channel
    guild = message.guild
    channel_id = channel.id
    user_id_str = str(message.author.id)

    if not guild:
        return
        
    guild_id = guild.id
    
    config = load_config()
    private_chats = config.get('private_chats', {})
    is_private_chat = (user_id_str in private_chats and private_chats[user_id_str] == channel_id)

    # อ่านไฟล์แนบและสร้างคำถาม
    question = message.content.strip()
    for attachment in message.attachments:
        text = await read_text_attachment(attachment)
        question += f"\n\n--- ไฟล์แนบ: {attachment.filename} ---\n{text}"
    
    auto_reply_channels = get_guild_setting(guild_id, 'auto_reply_channels')
    log_channel_id_str = get_guild_setting(guild_id, 'log_channel_id')

    # ===== Auto Reply Channel หรือ Private Chat =====
    if channel_id in auto_reply_channels or is_private_chat:
        if question.startswith(bot.command_prefix) or question.startswith('/'):
            return

        if not question.strip():
             return

        # ตรวจสอบยศสำหรับ Private Chat
        if is_private_chat and not check_allowed_role(message.author, guild.id):
            await message.channel.send("❌ การสนทนาส่วนตัวถูกจำกัดสิทธิ์ กรุณาติดต่อผู้ดูแลระบบเพื่อขอสิทธิ์")
            return

        typing_message = await message.channel.send(
             "⏳ กำลังประมวลผลคำถาม กรุณารอสักครู่...", delete_after=3
         )
        try:
             response_text = await call_api_async(question)
             await send_ai_response(message.channel, question, response_text, reply_to_message=message)
        finally:
             try: await typing_message.delete()
             except discord.NotFound: pass
        return

    # ===== Mention Bot =====
    if bot.user in message.mentions:
        
        # ตรวจสอบยศสำหรับการใช้บอทผ่านการ Mention 
        if not check_allowed_role(message.author, guild.id):
            if get_guild_setting(guild.id, 'allowed_role_ids'):
                await message.channel.send("❌ การใช้บอทผ่าน Mention ถูกจำกัดสำหรับบางยศเท่านั้น กรุณาสร้างห้องส่วนตัว")
                return
        
        question = message.clean_content.replace(f'@{bot.user.display_name}', '').strip()
        if not question:
            await message.channel.send("สวัสดีครับ ผมคือ **WormGPT** ถามได้เลย!")
            return

        typing_message = await message.channel.send(
            "⏳ กำลังประมวลผลคำถาม กรุณารอสักครู่...", delete_after=3
        )
        try:
            response_text = await call_api_async(question)
            await send_ai_response(message.channel, question, response_text, reply_to_message=message)
        finally:
            try: await typing_message.delete()
            except discord.NotFound: pass
        return


@tree.command(name="addchat", description="เสนอการเพิ่ม Channel ให้ตอบอัตโนมัติ (ส่งคำขอไปที่ช่อง Admin หลัก)")
async def add_chat_command(
    interaction: discord.Interaction,
    ช่องที่ต้องการเปิด: discord.TextChannel
):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        return
        
    approval_channel_id_str = get_guild_setting(guild_id, 'approval_channel_id')
    approval_channel_id = int(approval_channel_id_str) if approval_channel_id_str != "0" else 0

    ช่องสำหรับอนุมัติ = bot.get_channel(approval_channel_id)

    if approval_channel_id == 0 or not ช่องสำหรับอนุมัติ:
        await interaction.response.send_message(
            f"❌ ผู้ดูแลระบบยังไม่ได้ตั้งค่า Channel สำหรับอนุมัติ กรุณาใช้คำสั่ง **/set_id approval_channel <Channel ID>**",
            ephemeral=True
        )
        return

    auto_reply_channels = get_guild_setting(guild_id, 'auto_reply_channels')
    channel_id = ช่องที่ต้องการเปิด.id


    if channel_id in auto_reply_channels:
        await interaction.response.send_message(
            f"⚠️ {ช่องที่ต้องการเปิด.mention} เปิดใช้งานอยู่แล้ว",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"✅ ส่งคำขอเปิดใช้งาน WormGPT Auto-Reply ใน {ช่องที่ต้องการเปิด.mention} แล้ว\n"
        f"กรุณารอผู้ดูแลระบบกดปุ่ม 'ยืนยัน' ในช่อง **{ช่องสำหรับอนุมัติ.mention}** เพื่อเริ่มใช้งาน",
        ephemeral=True
    )

    view = ConfirmView(
        bot=bot,
        channel_to_add=ช่องที่ต้องการเปิด,
        original_author_id=interaction.user.id
    )

    embed = discord.Embed(
        title="⚠️ คำขอเปิดใช้งาน WormGPT Auto-Reply",
        description=(
            f"ผู้ใช้ **{interaction.user.display_name}** ได้ร้องขอให้เปิดใช้งานโหมดตอบกลับอัตโนมัติใน Channel **{ช่องที่ต้องการเปิด.mention}**\n"
            f"หากต้องการให้ WormGPT ตอบทุกข้อความในช่องดังกล่าว กรุณากดปุ่ม **✅ ยืนยันการเปิดใช้งาน**"
        ),
        color=MAIN_COLOR,
        timestamp=datetime.now()
    )
    embed.set_footer(text="ต้องมีสิทธิ์ Manage Channels เพื่อทำการยืนยัน (หมดเวลาใน 5 นาที)")

    public_message = await ช่องสำหรับอนุมัติ.send(embed=embed, view=view)
    view.message = public_message
    
@tree.command(name="delchat", description="[ADMIN] ปิดการใช้งาน Auto-Reply ใน Channel ที่ต้องการ")
@commands.has_permissions(administrator=True)
async def del_chat_command(
    interaction: discord.Interaction,
    ช่องที่ต้องการปิด: discord.TextChannel
):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        return

    if remove_auto_reply_channel(guild_id, ช่องที่ต้องการปิด.id):
        await interaction.response.send_message(
            f"✅ ปิดใช้งาน WormGPT Auto-Reply ใน {ช่องที่ต้องการปิด.mention} สำเร็จ",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"⚠️ {ช่องที่ต้องการปิด.mention} ไม่ได้เปิดใช้งาน WormGPT Auto-Reply",
            ephemeral=True
        )
        
@tree.command(name="delete_private_chat", description="ลบห้องแชทส่วนตัว WormGPT ของคุณ")
async def delete_private_chat_command(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id)
    config = load_config()
    private_chats = config.get('private_chats', {})

    if user_id_str not in private_chats:
        await interaction.response.send_message("⚠️ คุณไม่มีห้องส่วนตัวที่จะลบ", ephemeral=True)
        return

    channel_id = private_chats[user_id_str]
    channel = bot.get_channel(channel_id)
    
    if not channel:
        del config['private_chats'][user_id_str]
        save_config(config)
        await interaction.response.send_message("⚠️ ห้องส่วนตัวถูกลบไปแล้ว แต่ข้อมูลยังคงอยู่ในระบบ (ลบให้แล้ว)", ephemeral=True)
        return

    try:
        await interaction.response.defer(ephemeral=True)
        
        await channel.delete()
        del config['private_chats'][user_id_str]
        save_config(config)

        await interaction.followup.send(
            f"✅ ลบห้องส่วนตัว `{channel.name}` สำเร็จ",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.followup.send("❌ บอทไม่มีสิทธิ์ลบห้องนี้", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการลบห้อง: {e}", ephemeral=True)


if __name__ == "__main__":
    load_config()
    get_jailbreak_prompt()
    keep_alive()    # <--- เอามาวางแทรกไว้ตรงนี้สัด! (ใต้ load_config)
    print("🚀 Webview is Online!")

    if DISCORD_TOKEN == "MTQ2MTM2NDE0NjU1MjQ0MjkwMQ.GW_lVe.oZskrO2nugmBv8K2uA4ppOahmdYNVjJO1KiFeI":
        print("⚠️ Warning: DISCORD_TOKEN is still set to the default placeholder. Please update it.", file=sys.stderr)
    
    if WEBHOOK_URL == "":
        print("⚠️ Warning: WEBHOOK_URL is still set to the default placeholder. Please update it.", file=sys.stderr)

    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.LoginFailure:
        print("Invalid Discord Token!", file=sys.stderr)
    except Exception as e:

        print(f"Unexpected Error: {e}", file=sys.stderr)
