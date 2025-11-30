# --- 導入模組 ---
import discord
from discord.ext import commands, tasks 
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import json
from typing import Optional
import re 
import functools
import random 
import os
import time 
import requests 
from aiohttp import web
import logging
from discord.ui import View, Button

# 配置 logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord')

# 嘗試導入 AI 模組，如果失敗，AI 功能將禁用
try:
    from google import genai
    AI_ENABLED = True
except ImportError:
    print("⚠️ 找不到 'google-genai' 模組，AI 功能將無法使用。")
    AI_ENABLED = False
    class MockGenaiClient: 
        def __init__(self, **kwargs):
            pass
    genai = MockGenaiClient
    client = None


# --- 配置區塊 ---

# 檔案設定
TOKEN_FILE = 'token.txt'
AI_KEY_FILE = 'google_key.txt' 
CWA_KEY_FILE = 'cwa_key.txt'
SETTINGS_FILE = 'settings.json' 

# 指令前綴 (主要使用斜線指令，傳統指令前綴改為 '!')
PREFIX = '!' 

# 客服單設定
TICKET_CATEGORY_NAME = "🎫 客服單據"
TICKET_COUNTER = 0 

# 地震速報設定
EARTHQUAKE_CHECK_INTERVAL_SECONDS = 300 # 5 分鐘檢查一次
CWA_TOKEN = None
EARTHQUAKE_DATA_URL = "" # 初始為空

# 全域變數來儲存所有伺服器設定
server_settings = {} 

# 全域變數：動態語音頻道追蹤
# {guild_id: {created_channel_id: owner_id}}
DYNAMIC_CHANNELS = {} 

# --- 輔助函數：伺服器設定管理 & 時間解析 ---

def load_settings():
    """從 JSON 檔案載入所有伺服器設定"""
    global server_settings
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            server_settings = data.get('guild_settings', {})
        print(f"✅ 已載入 {len(server_settings)} 個伺服器的設定。")
    except FileNotFoundError:
        print(f"⚠️ 找不到 {SETTINGS_FILE} 檔案，將自動創建一個新的。")
        server_settings = {}
    except json.JSONDecodeError:
        print(f"❌ {SETTINGS_FILE} 檔案格式錯誤，使用空白設定。")
        server_settings = {}

def save_settings():
    """將所有伺服器設定儲存到 JSON 檔案"""
    global server_settings
    data = {'guild_settings': server_settings}
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ 儲存設定時發生錯誤: {e}")

def get_guild_settings(guild_id):
    """取得特定伺服器的設定，如果沒有則創建預設設定並儲存"""
    guild_id_str = str(guild_id) 
    
    # 建立預設設定並確保舊伺服器有新增的欄位
    default_settings = {
        "welcome_channel_id": None, 
        "admin_role_id": None,      
        "log_channel_id": None,     
        "ticket_role_id": None,
        "ai_channel_id": None,
        "role_buttons": [],
        "dynamic_voice_channel_id": None,
        "antispam_enabled": False,       
        "antispam_timeout_minutes": 10,
        "auto_role_id": None, 
        "earthquake_channel_id": None,  
        "earthquake_enabled": False,    
        "last_earthquake_time": None,   
    }

    if guild_id_str not in server_settings:
        server_settings[guild_id_str] = default_settings
        save_settings()
        return server_settings[guild_id_str]

    # 確保舊伺服器有新增的欄位
    changed = False
    for key, default_value in default_settings.items():
        if key not in server_settings[guild_id_str]:
            server_settings[guild_id_str][key] = default_value
            changed = True
            
    if changed:
        save_settings()
         
    return server_settings[guild_id_str]

def parse_time(time_str):
    """將時間字串 (e.g., '1h30m', '5d') 解析為秒數。"""
    time_str = time_str.lower().replace(' ', '')
    total_seconds = 0
    
    pattern = re.compile(r'(\d+)([dhms])')
    matches = pattern.findall(time_str)
    
    if not matches:
        raise ValueError("時間格式無效。請使用例如: 1d, 2h30m, 60s")
    
    for value_str, unit in matches:
        value = int(value_str)
        if unit == 'd':
            total_seconds += value * 86400 
        elif unit == 'h':
            total_seconds += value * 3600 
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 's':
            total_seconds += value
            
    MAX_SECONDS = 60 * 60 * 24 * 365 
    if total_seconds > MAX_SECONDS:
         raise ValueError("時間長度不能超過一年。")
    if total_seconds <= 0:
         raise ValueError("時間長度必須大於零。")
         
    return total_seconds

# --- 讀取密鑰與初始化 ---

load_settings()

try:
    with open(TOKEN_FILE, 'r') as file:
        TOKEN = file.read().strip()
except FileNotFoundError:
    print(f"錯誤：找不到 '{TOKEN_FILE}' 檔案。請創建並放入 Bot Token。")
    exit()

if AI_ENABLED:
    try:
        with open(AI_KEY_FILE, 'r') as file:
            GEMINI_API_KEY = file.read().strip()
        
        if not GEMINI_API_KEY:
            raise ValueError("API Key 為空")

        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Gemini AI 客戶端已使用 google_key.txt 初始化。")
        
    except FileNotFoundError:
        print(f"⚠️ 找不到 '{AI_KEY_FILE}' 檔案。AI 功能將無法運作。")
        client = None
        AI_ENABLED = False
    except ValueError:
        print(f"⚠️ '{AI_KEY_FILE}' 檔案內容為空。AI 功能將無法運作。")
        client = None
        AI_ENABLED = False
    except Exception as e:
        print(f"❌ 初始化 Gemini AI 客戶端失敗: {e}。AI 功能將無法運作。")
        client = None
        AI_ENABLED = False
else:
     client = None

# --- 讀取 CWA TOKEN ---
try:
    with open(CWA_KEY_FILE, 'r') as file:
        CWA_TOKEN = file.read().strip()
    if CWA_TOKEN and CWA_TOKEN != "請在這裡貼入您的 CWA Open Data API Key":
        # 使用真實的 API URL
        EARTHQUAKE_DATA_URL = f'https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0016-001?Authorization={CWA_TOKEN}&format=JSON&limit=1'
        print("✅ CWA Token 已載入，使用真實 API 接口。")
    else:
        print(f"⚠️ 找不到 CWA Token 或 Token 為空，地震速報功能將無法啟動。請在 {CWA_KEY_FILE} 中貼入 Key。")
        CWA_TOKEN = None
        
except FileNotFoundError:
    print(f"⚠️ 找不到 '{CWA_KEY_FILE}' 檔案。地震速報功能將無法啟動。")
    CWA_TOKEN = None

# --- 機器人 Intents 初始化 ---

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


# --- UI 類別：客服單按鈕 (Ticket View) ---

class TicketView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None) 
        self.bot = bot

    @discord.ui.button(label="開啟客服單", style=discord.ButtonStyle.green, custom_id="persistent_ticket_button", emoji="📩")
    async def open_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global TICKET_COUNTER
        await interaction.response.defer(ephemeral=True, thinking=True) 
        
        TICKET_COUNTER += 1
        ticket_name = f"單據-{interaction.user.name.lower().replace(' ', '-')}-{TICKET_COUNTER}" 

        settings = get_guild_settings(interaction.guild_id)
        ticket_role_id = settings.get('ticket_role_id')
        ticket_role = interaction.guild.get_role(ticket_role_id) if ticket_role_id else None

        category = discord.utils.get(interaction.guild.categories, name=TICKET_CATEGORY_NAME)
        if not category:
            try:
                category = await interaction.guild.create_category(
                    TICKET_CATEGORY_NAME,
                    overwrites={interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
                )
            except discord.Forbidden:
                return await interaction.followup.send("❌ 權限不足，無法創建客服類別。", ephemeral=True)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), 
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=False), 
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        
        mention_ticket_role = ""
        if ticket_role:
            overwrites[ticket_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
            mention_ticket_role = ticket_role.mention
        else:
             mention_ticket_role = "（請管理員使用 `/設定客服角色`）"

        try:
            existing_ticket = discord.utils.get(category.text_channels, topic=str(interaction.user.id))
            if existing_ticket:
                 return await interaction.followup.send(f"⚠️ 您已經有一個正在處理中的客服單：{existing_ticket.mention}", ephemeral=True)
            
            new_ticket_channel = await interaction.guild.create_text_channel(
                ticket_name, 
                category=category, 
                overwrites=overwrites,
                topic=str(interaction.user.id)
            )

            await new_ticket_channel.send(
                f"**客服通知：** {mention_ticket_role}\n歡迎 {interaction.user.mention}！您的客服單已開啟。\n"
                f"請描述您的問題，客服人員將盡快回覆您。\n"
                f"結束後請使用 `/關閉客服單` 關閉此單。"
            )
            await interaction.followup.send(f"✅ 您的客服單已開啟：{new_ticket_channel.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ 權限不足，無法創建客服單頻道。", ephemeral=True)


# --- 按鈕身分組 View (已修正為持久化) ---

class DynamicRoleButtonView(discord.ui.View):
    """動態生成身分組按鈕的 View (持久化版本)"""
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None) 
        self.bot = bot
        self.guild_id = guild_id 
        self.custom_id_prefix = f"persistent_role_assign_{self.guild_id}_"
        self._load_buttons() 
        
    @property
    def persistent(self) -> bool:
         return self.timeout is None

    def _load_buttons(self):
        """根據伺服器設定清單動態建立按鈕"""
        self.clear_items()
        
        settings = get_guild_settings(self.guild_id)
        settings_list = settings.get('role_buttons', [])
        
        if not settings_list:
             return

        for i, config in enumerate(settings_list):
            role_id = config.get('role_id')
            label = config.get('label', '領取身分組')
            emoji = config.get('emoji')
            
            custom_id = f"{self.custom_id_prefix}{role_id}"
            
            style = discord.ButtonStyle.secondary
            if i % 2 == 0:
                style = discord.ButtonStyle.primary

            button = discord.ui.Button(
                style=style,
                label=label,
                emoji=emoji,
                custom_id=custom_id 
            )
            button.callback = self.role_button_callback
            self.add_item(button)
            
    async def role_button_callback(self, interaction: discord.Interaction):
        """處理按鈕點擊事件，進行身分組的賦予或移除"""
        guild = interaction.guild 
        member = interaction.user
        
        try:
             # 從 custom_id 中解析出 role_id
             role_id_str = interaction.data['custom_id'].split('_')[-1]
             role_id = int(role_id_str)
        except (IndexError, ValueError):
             return await interaction.response.send_message("❌ 錯誤：按鈕內部 ID 解析失敗。", ephemeral=True)

        role = guild.get_role(role_id)

        if not role:
            # 如果找不到 role，嘗試清理設定
            settings = get_guild_settings(guild.id)
            settings['role_buttons'] = [
                config for config in settings['role_buttons'] if config['role_id'] != role_id
            ]
            save_settings()
            return await interaction.response.send_message("❌ 錯誤：找不到此身分組，配置已從設定中移除，請管理員重新發佈按鈕。", ephemeral=True)
            
        if role >= guild.me.top_role:
             return await interaction.response.send_message("❌ 機器人無法操作此身分組（身分組層級過高）。", ephemeral=True)

        if role in member.roles:
            # 移除
            try:
                await member.remove_roles(role, reason="持久化按鈕身分組：取消領取")
                await interaction.response.send_message(f"✅ 已移除您的身分組：**{role.name}**", ephemeral=True)
            except (discord.Forbidden, Exception) as e:
                 await interaction.response.send_message(f"❌ 移除身分組時發生錯誤: {e}", ephemeral=True)
        else:
            # 添加
            try:
                await member.add_roles(role, reason="持久化按鈕身分組：領取")
                await interaction.response.send_message(f"✅ 已成功領取身分組：**{role.name}**", ephemeral=True)
            except (discord.Forbidden, Exception) as e:
                 await interaction.response.send_message(f"❌ 賦予身分組時發生錯誤: {e}", ephemeral=True)


# --- 抽獎 View ---

class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = set()

    @discord.ui.button(label="參加抽獎", style=discord.ButtonStyle.red, custom_id="persistent_giveaway_join", emoji="🎉")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id in self.participants:
            await interaction.response.send_message("⚠️ 您已經參加過這次抽獎了！", ephemeral=True)
        else:
            self.participants.add(user_id)
            await interaction.response.send_message("✅ 已成功參加抽獎！", ephemeral=True)


# --- Cog 模組 ---

# 1. AI 智能回覆模組
class AICog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ai_client = genai.Client(api_key=AI_KEY) if AI_ENABLED else None
        self.chat_sessions = {} 

    def get_ai_response(self, prompt, client):
        """獲取 Gemini AI 的回覆"""
        model = 'gemini-2.5-flash'
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API 錯誤: {e}")
            return "❌ AI 服務目前無法回應，請稍後再試。"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        settings = load_settings()
        guild_settings = settings.get(str(message.guild.id), {})
        
        if AI_ENABLED and self.ai_client:
            
            is_ai_channel = message.channel.id == guild_settings.get('ai_channel_id')
            is_mentioned = self.bot.user in message.mentions
            
            if is_ai_channel or is_mentioned:
                
                message_content = message.content
                if is_mentioned:
                    message_content = re.sub(r'<@!?\d+>', '', message_content).strip()

                if not message_content:
                    await message.channel.send("您好，我是 Gemini AI 智能 Bot，請問有什麼可以為您服務的呢？", reference=message)
                    return

                try:
                    # 執行 AI 請求 (非同步)
                    ai_response = await asyncio.to_thread(self.get_ai_response, message_content, self.ai_client)
                    
                    # **已修改：將純文字回覆替換為 Embed 遷入訊息**
                    embed = discord.Embed(
                        title="🤖 Gemini AI 回覆",
                        description=ai_response,
                        color=discord.Color.from_rgb(0, 150, 255) 
                    )
                    
                    embed.set_footer(
                        text=f"回應給 {message.author.display_name}",
                        icon_url=message.author.display_avatar.url
                    )

                    await message.channel.send(embed=embed, reference=message)
                    
                    logger.info(f"AI 回覆成功: {ai_response[:50]}...")
                    
                except Exception as e:
                    logger.error(f"處理 AI 回覆失敗: {e}")
                    await message.channel.send("❌ 處理 AI 回覆時發生未知錯誤。", reference=message)

    @app_commands.command(name="設定智能回覆頻道", description="設定 AI 智能回覆的專屬頻道。")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_ai_channel(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        if not AI_ENABLED:
            await interaction.response.send_message("❌ AI 功能未啟用 (缺少 google-genai 模組或 Key)。", ephemeral=True)
            return

        settings = load_settings()
        settings.setdefault(str(interaction.guild_id), {})['ai_channel_id'] = 頻道.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ AI 智能回覆頻道已設定為 {頻道.mention}。", ephemeral=True)


# 3. 地震速報模組
class EarthquakeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_report_time = 0
        self.earthquake_check.start()

    def cog_unload(self):
        self.earthquake_check.cancel()

    @tasks.loop(seconds=300.0) # 每 5 分鐘檢查一次
    async def earthquake_check(self):
        if not CWA_KEY:
            return
            
        settings = load_settings()
        target_guild_ids = [int(guild_id) for guild_id, data in settings.items() 
                            if data.get('earthquake_channel_id') and data.get('earthquake_enabled')]
        
        if not target_guild_ids:
            return

        try:
            url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0016-001?Authorization={CWA_KEY}&format=JSON&limit=1"
            response = requests.get(url, timeout=10)
            response.raise_for_status() 
            data = response.json()
            
            if data['success'] != 'true':
                 logger.error(f"CWA API 呼叫失敗: {data.get('message')}")
                 return

            records = data['records']['Earthquake']
            if not records:
                return

            latest_eq = records[0]
            report_time_str = latest_eq['ReportTime']
            dt_object = datetime.strptime(report_time_str, '%Y-%m-%d %H:%M:%S')
            report_timestamp = dt_object.timestamp()

            if report_timestamp <= self.last_report_time:
                return

            self.last_report_time = report_timestamp

            # 提取地震資訊
            eq_info = latest_eq['EarthquakeInfo']
            eq_detail = eq_info['EarthquakeDetail']
            shakemap = eq_info['ShakingArea']['WidgetItem']
            
            mag = eq_detail['Magnitude']['MagnitudeValue']
            epicenter = eq_detail['Epicenter']['Location']
            depth = eq_detail['Epicenter']['Depth']['Value']
            
            max_shaking = max(s['AreaIntensity']['CWA']['text'] for s in shakemap)
            
            # 構建 Embed
            embed = discord.Embed(
                title=f"🚨 台灣地震速報 - 規模 {mag}",
                description=f"**震央：** {epicenter}\n**深度：** {depth} 公里\n**最大震度：** {max_shaking}",
                color=discord.Color.red(),
                timestamp=dt_object
            )
            embed.set_footer(text=f"資料來源: 中央氣象署 | 報告時間: {report_time_str}")

            # 發送給所有設定的伺服器
            for guild_id in target_guild_ids:
                channel_id = settings[str(guild_id)]['earthquake_channel_id']
                channel = self.bot.get_channel(channel_id)
                if channel:
                    try:
                        await channel.send("@everyone 新地震報告！", embed=embed)
                    except discord.Forbidden:
                        logger.warning(f"無法在伺服器 {guild_id} 的頻道 {channel.id} 發送地震速報 (權限不足)。")
                        
        except requests.exceptions.RequestException as e:
            logger.error(f"CWA API 連線錯誤: {e}")
        except Exception as e:
            logger.error(f"地震速報檢查失敗: {e}")

    @app_commands.command(name="設定地震頻道", description="設定地震速報將發布的頻道。")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_earthquake_channel(self, interaction: discord.Interaction, 頻道: discord.TextChannel):
        if not CWA_KEY:
            await interaction.response.send_message("❌ 地震速報功能未啟用 (缺少 CWA Key)。", ephemeral=True)
            return
            
        settings = load_settings()
        settings.setdefault(str(interaction.guild_id), {})['earthquake_channel_id'] = 頻道.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ 地震速報頻道已設定為 {頻道.mention}。", ephemeral=True)

    @app_commands.command(name="開啟地震速報", description="啟用本地震速報功能。")
    @app_commands.checks.has_permissions(administrator=True)
    async def enable_earthquake(self, interaction: discord.Interaction):
        if not CWA_KEY:
            await interaction.response.send_message("❌ 地震速報功能未啟用 (缺少 CWA Key)。", ephemeral=True)
            return

        settings = load_settings()
        if not settings.get(str(interaction.guild_id), {}).get('earthquake_channel_id'):
            await interaction.response.send_message("⚠️ 請先使用 `/設定地震頻道` 設定一個頻道。", ephemeral=True)
            return
            
        settings.setdefault(str(interaction.guild_id), {})['earthquake_enabled'] = True
        save_settings(settings)
        await interaction.response.send_message("✅ 地震速報已開啟。", ephemeral=True)

    @app_commands.command(name="關閉地震速報", description="禁用本地震速報功能。")
    @app_commands.checks.has_permissions(administrator=True)
    async def disable_earthquake(self, interaction: discord.Interaction):
        settings = load_settings()
        settings.setdefault(str(interaction.guild_id), {})['earthquake_enabled'] = False
        save_settings(settings)
        await interaction.response.send_message("✅ 地震速報已關閉。", ephemeral=True)


# --- 事件監聽 (Events) ---

@bot.event
async def on_ready():
    """機器人啟動完成事件，並同步斜線指令"""
    print(f'機器人已上線：{bot.user} (ID: {bot.user.id})')
    print('正在同步斜線指令...')
    
    # 載入持久化 View
    bot.add_view(TicketView(bot))
    
    # 載入持久化身分組按鈕 View
    for guild_id_str in server_settings.keys():
        try:
            guild_id = int(guild_id_str)
            view = DynamicRoleButtonView(bot, guild_id)
            if view.children: 
                bot.add_view(view)
                print(f"✅ 已為伺服器 {guild_id} 載入 {len(view.children)} 個持久化身分組按鈕。")
        except Exception as e:
            print(f"❌ 載入伺服器 {guild_id_str} 的持久化按鈕失敗: {e}") 
            
# --- 載入 Cog ---
    try:
        # 1. 載入內部定義的 Cog (直接使用 bot.add_cog)
        # 這裡假設 EarthquakeCog 和 AcrossGroupsCog 是在 main.py 內部定義的
        # 請確保 EarthquakeCog 和 AcrossGroupsCog 類別已在 main.py 或其他地方正確定義
        await bot.add_cog(EarthquakeCog(bot))  
        
        print("✅ 內部 Cog (EarthquakeCog, AcrossGroupsCog) 已載入。")
        
        # 2. 載入外部檔案定義的 Cog (必須使用 load_extension)
        # 💥 修正：確保列表中包含您所有的外部 Cog 檔案名稱 (不含 .py)
        external_cogs = [
            'MusicLavalink', 
            'GlobalBan',
            'RaidProtect'
        ]

        for cog_name in external_cogs:
            await bot.load_extension(cog_name)
            print(f"✅ 外部 Cog '{cog_name}' 已載入。")
            
    except Exception as e:
        # 載入失敗時，最好明確指出是哪裡出錯
        print(f"❌ Cog 載入失敗: {e}")
        
    try:
        # 3. 同步斜線指令 (放在所有 Cog 載入後)
        synced = await bot.tree.sync()
        print(f"✅ 已同步 {len(synced)} 個斜線指令。")
    except Exception as e:
        print(f"❌ 斜線指令同步失敗: {e}")
        
    print('------')
    await bot.change_presence(activity=discord.Game(name=f"使用 /指令清單 尋求幫助"))

@bot.event
async def on_guild_join(guild):
    """機器人加入新伺服器時的初始化"""
    print(f"機器人加入新伺服器: {guild.name} (ID: {guild.id})")
    get_guild_settings(guild.id)
    
    try:
        view = DynamicRoleButtonView(bot, guild.id)
        if view.children: 
            bot.add_view(view)
    except Exception as e:
         print(f"❌ 新伺服器 {guild.name} 載入持久化按鈕失敗: {e}")

    try:
        channel_name = "機器人也想下班-說明"
        first_channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        new_channel = await guild.create_text_channel(channel_name)
    except discord.Forbidden:
        if first_channel:
             await first_channel.send(f"⚠️ 權限不足，無法創建說明頻道 '{channel_name}'。請給予我 '管理頻道' 的權限。", delete_after=15)
        print(f"無法在 {guild.name} 創建頻道。權限不足。")
        return
    except Exception:
         return 

    welcome_embed = discord.Embed(
        title="機器人也想下班幫助說明",
        description="您好！感謝你使用 機器人也想下班",
        color=0x00ff00
    )
    welcome_embed.add_field(name="重要信息:", value="可使用指令 `/指令清單` 查看機機器人的指令內容", inline=False)
    welcome_embed.add_field(name="功能概述:", value="本機器人具有AI智能回復、各種防護、客戶單系統、各種遊戲娛樂功能。", inline=False)
    
    action_message = (
        "此頻道為引導頻道閱後即可刪除。\n"
        "最後感謝您的使用，如有問題可點擊[機器人也想下班](https://discord.gg/v6YtWEdZ3U)加入群組後詢問。\n"
        "更可在群組內得知有關 [點我進入官網](https://discord-bot-gr53qi.lumi.ing/) 機器人也想下班 新相關資訊。"
    )
    
    welcome_embed.set_footer(text=f"感謝使用 <@{bot.user.id}> 製作此機器人。")

    await new_channel.send(embed=welcome_embed)
    await new_channel.send(action_message)
    print(f"已在 {guild.name} 成功發送歡迎訊息到頻道 {new_channel.name}")

@bot.event
async def on_member_join(member):
    """自動化任務: 自動歡迎 **及自動賦予身分組**"""
    settings = get_guild_settings(member.guild.id)
    
    # -----------------------------------------------------
    # 自動賦予身分組
    # -----------------------------------------------------
    auto_role_id = settings.get('auto_role_id')
    if auto_role_id:
        auto_role = member.guild.get_role(auto_role_id)
        
        if auto_role:
            if auto_role >= member.guild.me.top_role:
                 print(f"❌ 警告：在 {member.guild.name} 中，無法自動賦予身分組 '{auto_role.name}'，層級高於機器人。")
            else:
                try:
                    await member.add_roles(auto_role, reason="新成員自動身分組")
                    print(f"✅ 在 {member.guild.name} 中成功為 {member.name} 賦予身分組 '{auto_role.name}'。")
                except discord.Forbidden:
                    print(f"❌ 警告：在 {member.guild.name} 中，無法自動賦予身分組 '{auto_role.name}'，權限不足。")
                except Exception as e:
                     print(f"❌ 賦予身分組時發生未知錯誤: {e}")

# --- 事件：機器人準備就緒 ---
    async def on_ready(self):
        """當機器人完成登入並準備就緒時觸發"""
        global LAST_SYNC_TIME
        
        # 打印上線信息
        print(f'機器人已上線：{self.user.name}#{self.user.discriminator} (ID: {self.user.id})')

        # 檢查是否需要同步指令
        if LAST_SYNC_TIME is None or (datetime.now() - LAST_SYNC_TIME) > timedelta(hours=1):
            await self.sync_commands_task()
        
        # ⬇️ 精確整合：設置機器人狀態為 閒置 (Idle - 月亮圖標) ⬇️
        try:
            # 這裡使用 self.user.name 作為初始活動名稱
            await self.change_presence(
                status=discord.Status.idle,             
                activity=discord.Game(name=self.user.name) 
            )
            print("✅ 機器人狀態已成功設定為 '閒置' (Idle/月亮)")
        except Exception as e:
            logger.error(f"❌ 設定狀態時發生錯誤: {e}")
        # ⬆️ 精確整合：設置機器人狀態為 閒置 (Idle - 月亮圖標) ⬆️

        print('--------------------------')

    # -----------------------------------------------------
    # 歡迎訊息邏輯
    # -----------------------------------------------------
    welcome_channel = None

    if settings.get('welcome_channel_id'):
        welcome_channel = member.guild.get_channel(settings['welcome_channel_id'])
    
    if not welcome_channel:
        welcome_channel = member.guild.system_channel or next((c for c in member.guild.text_channels if c.permissions_for(member.guild.me).send_messages), None)
    
    if welcome_channel:
        welcome_embed = discord.Embed(
            title="👋 歡迎新成員！",
            description=f"熱烈歡迎 {member.mention} 加入 **{member.guild.name}**！\n\n歡迎來到**{member.guild.name}*伺服器\n在這裡，你可以做各種你想做的事!\n- 但請不要違反此伺服器規則", 
            color=discord.Color.blue()
        )
        
        welcome_embed.set_thumbnail(url=member.display_avatar.url)
        welcome_embed.set_footer(text=f"這是您的第 {len(member.guild.members)} 位成員！")
        
        await welcome_channel.send(content=f"嗨，{member.mention}！", embed=welcome_embed)

@bot.event
async def on_message(message):
    """處理 AI 聊天和防刷屏 (主要處理函數)"""
    if message.author.bot:
        return

    if not message.guild:
        # 私訊處理
        await bot.process_commands(message)
        return
        
    settings = get_guild_settings(message.guild.id)
    
    # 1. AI 聊天邏輯
    if AI_ENABLED and client:
        should_reply_ai = False
        user_question = message.content

        # 模式 1: 提及 Bot (@他)
        if bot.user.mentioned_in(message):
            user_question = re.sub(r'<@!?\d+>', '', message.content).strip()
            if user_question:
                 should_reply_ai = True
        
        # 模式 2: 在專屬 AI 頻道發言
        elif settings.get('ai_channel_id') == message.channel.id:
            should_reply_ai = True

        if should_reply_ai and user_question:
            # 安全修復：禁用所有提及
            safe_mentions = discord.AllowedMentions(
                everyone=False,
                users=False, 
                roles=False 
            )
            async with message.channel.typing():
                try:
                    response = client.models.generate_content(model='gemini-2.5-flash', contents=user_question)
                    if response.text:
                        await message.reply(response.text, mention_author=False, allowed_mentions=safe_mentions) 
                    else:
                        await message.reply("抱歉，我無法理解您的問題。", mention_author=False, allowed_mentions=safe_mentions)
                except Exception as e:
                    print(f"AI 回覆時發生錯誤: {e}")
                    await message.reply("❌ AI 服務發生錯誤。", mention_author=False, allowed_mentions=safe_mentions)
            if settings.get('ai_channel_id') == message.channel.id:
                return
    
    # 2. 防刷屏系統
    if settings.get("antispam_enabled"):
        content = message.content.lower()
        timeout_minutes = settings.get("antispam_timeout_minutes", 10) 
        
        if len(content) > 20:
            most_common = max(set(content), key=content.count, default='')
            if most_common and content.count(most_common) / len(content) > 0.5:
                
                try:
                    await message.delete()
                except discord.Forbidden:
                    await message.channel.send(f"⚠️ {message.author.mention}：請勿刷屏！機器人沒有刪除訊息的權限。", delete_after=5)
                    await bot.process_commands(message) 
                    return
                
                try:
                    duration = discord.utils.utcnow() + timedelta(minutes=timeout_minutes)
                    await message.author.timeout(duration, reason=f"自動防刷屏：重複字元刷屏 (Timeout {timeout_minutes}m)")
                    await message.channel.send(
                        f"🚫 防刷屏系統啟用：{message.author.mention} 因刷屏被禁言 **{timeout_minutes} 分鐘**。", 
                        delete_after=10
                    )
                except discord.Forbidden:
                    pass
                


# --- 動態語音頻道事件處理 ---
@bot.event
async def on_voice_state_update(member, before, after):
    """處理動態語音頻道的創建與刪除"""
    if member.bot or not member.guild:
        return

    guild_id = member.guild.id
    settings = get_guild_settings(guild_id)
    creation_channel_id = settings.get("dynamic_voice_channel_id")
    
    if guild_id not in DYNAMIC_CHANNELS:
        DYNAMIC_CHANNELS[guild_id] = {}

    # 1. 創建臨時頻道 (加入 Creation Channel)
    if after.channel and after.channel.id == creation_channel_id:
        category = after.channel.category
        new_channel_name = f"🎧 {member.name} 的頻道"
        
        try:
            new_channel = await member.guild.create_voice_channel(
                name=new_channel_name,
                category=category,
                user_limit=after.channel.user_limit,
                bitrate=after.channel.bitrate
            )
            await member.move_to(new_channel)
            DYNAMIC_CHANNELS[guild_id][new_channel.id] = member.id
            
        except discord.Forbidden:
            print(f"❌ 權限不足，無法在 {member.guild.name} 創建或移動語音頻道。")
        except Exception as e:
            print(f"❌ 創建臨時頻道時發生錯誤: {e}")
            
    # 2. 刪除臨時頻道 (舊頻道變空)
    if before.channel and before.channel.id in DYNAMIC_CHANNELS[guild_id]:
        if before.channel.id != creation_channel_id: 
            if not before.channel.members: 
                try:
                    await before.channel.delete(reason="動態語音頻道：頻道為空，自動刪除")
                    del DYNAMIC_CHANNELS[guild_id][before.channel.id]
                    print(f"✅ 已刪除空置的動態語音頻道: {before.channel.name}")
                except discord.Forbidden:
                    print(f"❌ 權限不足，無法刪除動態語音頻道: {before.channel.name}")
                except Exception as e:
                    print(f"❌ 刪除動態語音頻道時發生錯誤: {e}")


# --- 伺服器設定指令 (管理員專用) ---

@bot.tree.command(name="設定歡迎頻道", description="設定歡迎訊息發送的頻道 (管理員專用)")
@app_commands.describe(頻道="用於發送歡迎訊息的頻道")
@app_commands.checks.has_permissions(administrator=True)
async def 設定歡迎頻道(interaction: discord.Interaction, 頻道: discord.TextChannel):
    settings = get_guild_settings(interaction.guild_id)
    settings['welcome_channel_id'] = 頻道.id
    save_settings()
    await interaction.response.send_message(f"✅ 歡迎訊息頻道已設定為 {頻道.mention}。", ephemeral=True)


@bot.tree.command(name="設定自動身分組", description="設定新加入成員將自動獲得的單一身分組 (管理員專用)。")
@app_commands.describe(角色="新成員將自動獲得的身分組")
@app_commands.checks.has_permissions(administrator=True)
async def 設定自動身分組(interaction: discord.Interaction, 角色: discord.Role):
    
    if 角色 >= interaction.guild.me.top_role:
        return await interaction.response.send_message("❌ 錯誤：該身分組層級高於機器人，無法進行操作。", ephemeral=True)

    settings = get_guild_settings(interaction.guild_id)
    settings['auto_role_id'] = 角色.id
    save_settings()
    await interaction.response.send_message(
        f"✅ 新成員自動身分組已設定為 {角色.mention}。", 
        ephemeral=True
    )

@bot.tree.command(name="清除自動身分組", description="清除新成員自動身分組的設定 (管理員專用)。")
@app_commands.checks.has_permissions(administrator=True)
async def 清除自動身分組(interaction: discord.Interaction):
    settings = get_guild_settings(interaction.guild_id)
    settings['auto_role_id'] = None
    save_settings()
    await interaction.response.send_message(f"✅ 新成員自動身分組設定已清除。", ephemeral=True)


@bot.tree.command(name="設定客服角色", description="設定哪個角色是客服人員，以便其能看到客服單 (管理員專用)")
@app_commands.describe(角色="擁有此角色的成員將能看到並回覆客服單")
@app_commands.checks.has_permissions(administrator=True)
async def 設定客服角色(interaction: discord.Interaction, 角色: discord.Role):
    settings = get_guild_settings(interaction.guild_id)
    settings['ticket_role_id'] = 角色.id
    save_settings()
    await interaction.response.send_message(f"✅ 客服單處理角色已設定為 {角色.mention}。請記得使用 /發布客服按鈕。", ephemeral=True)

@bot.tree.command(name="發布客服按鈕", description="在指定頻道發布一個公開的客服單開啟按鈕 (管理員專用)")
@app_commands.describe(頻道="發布按鈕的頻道")
@app_commands.checks.has_permissions(administrator=True)
async def 發布客服按鈕(interaction: discord.Interaction, 頻道: discord.TextChannel):
    embed = discord.Embed(
        title="📩 客服單據與問題回報",
        description="如果您有任何疑問、回報 Bug 或需要協助，請點擊下方的 **[開啟客服單]** 按鈕。",
        color=0x3498db
    )
    await 頻道.send(embed=embed, view=TicketView(bot))
    await interaction.response.send_message(f"✅ 客服單按鈕已成功發布到 {頻道.mention}。", ephemeral=True)

@bot.tree.command(name="設定智能回覆頻道", description="設定 AI 專屬頻道 (管理員專用)")
@app_commands.describe(頻道="設定 AI 專屬頻道，用戶在該頻道發言 Bot 會自動回覆。")
@app_commands.checks.has_permissions(administrator=True)
async def 設定_AI_頻道(interaction: discord.Interaction, 頻道: discord.TextChannel):
    if not AI_ENABLED:
         return await interaction.response.send_message("❌ AI 功能未啟用 (請檢查 google-genai 模組和 key)。", ephemeral=True)

    settings = get_guild_settings(interaction.guild_id)
    settings['ai_channel_id'] = 頻道.id
    save_settings()
    await interaction.response.send_message(f"✅ AI 智能回覆專屬頻道已設定為 {頻道.mention}。\n在該頻道中，用戶發送非指令訊息時，Bot 將會自動回覆。", ephemeral=True)

@bot.tree.command(name="開關防刷屏", description="開關防刷屏系統，並設定刷屏後的禁言時間 (管理員專用)。")
@app_commands.describe(
    開關="選擇 '開啟' 或 '關閉'", 
    禁言時間="刷屏後禁言分鐘數 (1-40320 分鐘，預設 10 分鐘)"
)
@app_commands.choices(開關=[
    app_commands.Choice(name="開啟", value="on"),
    app_commands.Choice(name="關閉", value="off")
])
@app_commands.checks.has_permissions(administrator=True)
async def 開關防刷屏(interaction: discord.Interaction, 開關: str, 禁言時間: app_commands.Range[int, 1, 40320] = 10):
    settings = get_guild_settings(interaction.guild_id)
    
    is_enabled = 開關 == "on"
    settings['antispam_enabled'] = is_enabled
    settings['antispam_timeout_minutes'] = 禁言時間
    save_settings()

    if is_enabled:
        await interaction.response.send_message(
            f"✅ 防刷屏系統已 **開啟**。\n"
            f"觸發刷屏的用戶將被禁言 **{禁言時間} 分鐘**。", 
            ephemeral=True
        )
    else:
        await interaction.response.send_message("✅ 防刷屏系統已 **關閉**。", ephemeral=True)


# --- 動態語音頻道設定指令 ---

@bot.tree.command(name="設定動態語音頻道", description="設定一個語音頻道作為動態頻道創建的入口 (管理員專用)。")
@app_commands.describe(頻道="用戶進入此頻道後，Bot 會自動為其創建新頻道。")
@app_commands.checks.has_permissions(administrator=True)
async def 設定動態語音頻道(interaction: discord.Interaction, 頻道: discord.VoiceChannel):
    settings = get_guild_settings(interaction.guild_id)
    settings['dynamic_voice_channel_id'] = 頻道.id
    save_settings()
    await interaction.response.send_message(
        f"✅ 動態語音頻道創建入口已設定為 **{頻道.name}**。\n用戶進入此頻道時，將自動創建一個臨時語音頻道。", 
        ephemeral=True
    )

@bot.tree.command(name="清除動態語音頻道", description="清除動態語音頻道入口的設定 (管理員專用)。")
@app_commands.checks.has_permissions(administrator=True)
async def 清除動態語音頻道(interaction: discord.Interaction):
    settings = get_guild_settings(interaction.guild_id)
    settings['dynamic_voice_channel_id'] = None
    save_settings()
    await interaction.response.send_message(f"✅ 動態語音頻道創建入口已清除。", ephemeral=True)


# --- 單一按鈕身分組配置指令 ---

@bot.tree.command(name="發布身分組按鈕", description="清除舊配置，發布一個全新的身分組領取按鈕 (永久)。") 
@app_commands.describe(
    頻道="發布按鈕的頻道", 
    身分組="點擊按鈕將賦予或移除的身分組", 
    標題="嵌入訊息的標題",
    自訂訊息="嵌入訊息的內文 (提示說明)", 
    按鈕文字="按鈕上顯示的文字標籤"
)
@app_commands.checks.has_permissions(administrator=True)
async def 發布身分組按鈕(interaction: discord.Interaction, 
                           頻道: discord.TextChannel, 
                           身分組: discord.Role, 
                           標題: app_commands.Range[str, 1, 100], 
                           自訂訊息: app_commands.Range[str, 1, 1024], 
                           按鈕文字: app_commands.Range[str, 1, 80] = "領取身分組"):
    
    await interaction.response.defer(ephemeral=True)

    settings = get_guild_settings(interaction.guild_id)
    
    if 身分組 >= interaction.guild.me.top_role:
         return await interaction.followup.send("❌ 錯誤：該身分組層級高於機器人，無法進行操作。", ephemeral=True)

    # 清除所有舊的按鈕配置 (只允許一個按鈕，簡化持久化邏輯)
    settings['role_buttons'] = []
    
    new_config = {
        "role_id": 身分組.id,
        "label": 按鈕文字,
        "emoji": None 
    }
    settings['role_buttons'].append(new_config)
    save_settings()
    
    # 重新載入持久化 View
    role_view = DynamicRoleButtonView(bot, interaction.guild_id)
    try:
        if role_view.children: 
             bot.add_view(role_view) 
    except Exception as e:
         print(f"❌ 重新載入持久化按鈕失敗: {e}")

    # 建立 Embed 訊息
    embed = discord.Embed(
        title=標題,
        description=f"{自訂訊息}\n\n**身分組名稱：** {身分組.mention}",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"點擊按鈕領取或移除身分組 | 發布者: {interaction.user.name}")

    # 發送訊息和按鈕
    try:
        await 頻道.send(embed=embed, view=role_view)
        await interaction.followup.send(f"✅ 身分組按鈕 (身分組: {身分組.name}) 已成功發布到 {頻道.mention}。", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(f"❌ 機器人沒有權限在 {頻道.mention} 發送訊息。", ephemeral=True)


# --- 核心指令 ---

@bot.tree.command(name="指令清單", description="查看機器人的所有斜線指令和說明。")
async def 指令清單(interaction: discord.Interaction):
    help_embed = discord.Embed(
        title="🤖 機器人也想下班 - 指令清單",
        description="以下是本機器人提供的主要斜線指令 (Slash Commands)：",
        color=0x4a90e2
    )
    
    ai_status = "`/智能回覆`, `/擲骰子`, `/發起投票`\n*AI 可在專屬頻道或提及 Bot (@他) 使用*"
    if not AI_ENABLED:
        ai_status = "*AI 功能目前未啟用或 Key 未設置*"

    help_embed.add_field(name="**AI / 娛樂**", value=ai_status, inline=False)
    help_embed.add_field(name="**管理 / 實用**", value="`/發布公告`, `/禁言`, `/用戶資料查詢`, `/大量刪除訊息`, `/延遲`", inline=False) 
    help_embed.add_field(name="**✨ 伺服器配置與自動化**", value=(
        "`/發布身分組按鈕` (永久按鈕領取)\n"
        "`/設定動態語音頻道`, `/清除動態語音頻道`\n"
        "`/開關防刷屏` (防刷屏設定)\n"
        "`/設定自動身分組`, `/清除自動身分組` (新成員自動賦予身分組)\n"
        "`/計時器`, `/抽獎`"
    ), inline=False) 
    
    help_embed.add_field(name="**系統 / 設定**", value=(
        "`/設定歡迎頻道`, `/設定智能回覆頻道`\n"
        "`/設定客服角色`, `/發布客服按鈕`, `/關閉客服單`\n"
        "`/設定地震頻道`, `/開啟地震速報`, `/關閉地震速報`\n"
    ), inline=False)
    
    help_embed.set_footer(text=f"所有指令皆以 / 開頭。")
    await interaction.response.send_message(embed=help_embed, ephemeral=False)

# --- 延遲指令 (全局指令) ---
@bot.tree.command(name="延遲", description="檢查機器人與 Discord 伺服器之間的連線延遲 (Ping值)。")
async def latency_command(interaction: discord.Interaction):
    ping_ms = round(bot.latency * 1000)
    
    if ping_ms < 100:
        color = discord.Color.green()
    elif ping_ms < 250:
        color = discord.Color.gold()
    else:
        color = discord.Color.red()
        
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"目前延遲：**{ping_ms} ms**",
        color=color
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="智能回覆", description="使用 Google Gemini AI 智能回覆您的問題。")
@app_commands.describe(問題="您想問 AI 的問題。")
async def 智能回覆(interaction: discord.Interaction, 問題: str):
    if not client:
        return await interaction.response.send_message("❌ AI 服務尚未初始化成功 (請檢查 google_key.txt)。", ephemeral=True)
    await interaction.response.defer()
    
    safe_mentions = discord.AllowedMentions(
        everyone=False,
        users=False,
        roles=False
    )
    
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=問題)
        if response.text:
            await interaction.followup.send(response.text, allowed_mentions=safe_mentions) 
        else:
            await interaction.followup.send("抱歉，我無法生成有效的回答。", allowed_mentions=safe_mentions)
    except Exception as e:
        await interaction.followup.send("❌ AI 服務發生錯誤。", allowed_mentions=safe_mentions)

@bot.tree.command(name='大量刪除訊息', description="批量刪除當前頻道中最多 100 條訊息 (14天內)。")
@app_commands.describe(數量="要刪除的訊息數量 (1-100)", 頻道="要刪除訊息的頻道 (可選, 預設為當前頻道)")
@app_commands.checks.has_permissions(manage_messages=True)
async def 大量刪除訊息(interaction: discord.Interaction, 數量: app_commands.Range[int, 1, 100], 頻道: Optional[discord.TextChannel] = None):
    
    target_channel = 頻道 or interaction.channel
        
    if not target_channel.permissions_for(interaction.guild.me).manage_messages:
        return await interaction.response.send_message(f"❌ 我沒有權限在 {target_channel.mention} 管理和刪除訊息。", ephemeral=True)
        
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        deleted = await target_channel.purge(limit=數量)
        await interaction.followup.send(
            f"✅ 已在 {target_channel.mention} 成功刪除 **{len(deleted)}** 條訊息。", 
            ephemeral=False, 
            delete_after=10
        )
    except discord.Forbidden:
        await interaction.followup.send("❌ 權限不足，無法執行批量刪除。", ephemeral=True)
    except discord.HTTPException as e:
         if "14 days old" in str(e):
              await interaction.followup.send("❌ 錯誤：Discord 無法批量刪除超過 14 天的訊息。", ephemeral=True)
         else:
              await interaction.followup.send(f"❌ 刪除訊息時發生錯誤: {e}", ephemeral=True)

@bot.tree.command(name='計時器', description='設定一個計時器，時間到時提醒您。')
@app_commands.describe(時間長度="計時器持續時間 (例如: 1h, 30m, 5s)", 提醒事項="時間到時的提醒內容 (可選)")
async def 計時器(interaction: discord.Interaction, 時間長度: str, 提醒事項: Optional[str] = "時間到囉！"):
    
    await interaction.response.defer(ephemeral=False)
    
    try:
        duration_seconds = parse_time(時間長度)
    except ValueError as e:
        return await interaction.followup.send(f"❌ 時間格式錯誤: {e}", ephemeral=True)

    end_time = datetime.now() + timedelta(seconds=duration_seconds)
    
    m, s = divmod(duration_seconds, 60)
    h, m = divmod(m, 60)
    time_display = f"{h} 小時 {m} 分鐘 {s} 秒"
    
    embed = discord.Embed(
        title="⏱️ 計時器啟動",
        description=f"✅ 計時器已設定！",
        color=discord.Color.gold()
    )
    embed.add_field(name="持續時間", value=time_display, inline=True)
    embed.add_field(name="結束時間", value=f"<t:{int(end_time.timestamp())}:F> (<t:{int(end_time.timestamp())}:R>)", inline=False)
    embed.add_field(name="提醒事項", value=提醒事項, inline=False)
    embed.set_footer(text=f"由 {interaction.user.name} 發起")

    await interaction.followup.send(embed=embed)

    await asyncio.sleep(duration_seconds)

    reminder_embed = discord.Embed(
        title="🚨 計時器結束！",
        description=f"{interaction.user.mention}，您設定的計時器 ({time_display}) 已經結束！",
        color=discord.Color.red()
    )
    reminder_embed.add_field(name="提醒事項", value=提醒事項, inline=False)
    
    try:
        await interaction.channel.send(content=f"{interaction.user.mention}", embed=reminder_embed)
    except Exception as e:
        print(f"❌ 發送計時器提醒時發生錯誤: {e}")


@bot.tree.command(name='抽獎', description="發起一個限時抽獎活動。")
@app_commands.describe(
    獎品="抽獎的獎品內容", 
    時間長度="抽獎持續時間 (例如: 1h, 30m, 5d)", 
    獲勝者數量="將抽出多少獲勝者 (預設 1)"
)
@app_commands.checks.has_permissions(administrator=True)
async def 抽獎(interaction: discord.Interaction, 獎品: str, 時間長度: str, 獲勝者數量: app_commands.Range[int, 1, 10] = 1):
    
    try:
        duration_seconds = parse_time(時間長度)
    except ValueError as e:
        return await interaction.response.send_message(f"❌ 時間格式錯誤: {e}", ephemeral=True)

    end_time = datetime.now() + timedelta(seconds=duration_seconds)
    
    embed = discord.Embed(
        title=f"🎉 抽獎活動：{獎品} 🎉",
        description=f"點擊下方 **[參加抽獎]** 按鈕即可參加。\n\n**結束時間:** <t:{int(end_time.timestamp())}:R>\n**獲勝者:** {獲勝者數量} 位",
        color=discord.Color.red()
    )
    embed.set_footer(text=f"抽獎由 {interaction.user.name} 發起")

    giveaway_view = GiveawayView()
    
    await interaction.response.send_message(content="**🎉 抽獎開始！** @everyone", embed=embed, view=giveaway_view)
    
    giveaway_message = await interaction.original_response()

    await asyncio.sleep(duration_seconds)

    for item in giveaway_view.children:
        item.disabled = True
    
    try:
        await giveaway_message.edit(view=giveaway_view)
    except Exception as e:
        print(f"❌ 禁用按鈕時發生錯誤: {e}")

    participants = list(giveaway_view.participants)
    
    if len(participants) < 獲勝者數量:
        final_embed = discord.Embed(
            title=f"😭 抽獎已結束：{獎品} 😭",
            description=f"參與人數不足 (**{len(participants)}** 人)，無法抽出 {獲勝者數量} 位獲勝者。\n下次再來吧！",
            color=discord.Color.dark_red()
        )
        await giveaway_message.reply(embed=final_embed)
        return

    winners_id = random.sample(participants, 獲勝者數量)
    winners_mentions = []
    
    for winner_id in winners_id:
        winner = interaction.guild.get_member(winner_id)
        if winner:
            winners_mentions.append(winner.mention)
    
    winners_text = "\n".join(winners_mentions)
    
    final_embed = discord.Embed(
        title=f"🏆 抽獎結果公佈：{獎品} 🏆",
        description=f"恭喜以下 **{獲勝者數量} 位** 幸運兒贏得了 **{獎品}**！",
        color=discord.Color.green()
    )
    final_embed.add_field(name="👑 獲勝者名單", value=winners_text, inline=False)

    await giveaway_message.reply(content=f"**恭喜 {', '.join(winners_mentions)} 獲獎！**", embed=final_embed)


@bot.tree.command(name='發布公告', description="發送公告到指定頻道。")
@app_commands.describe(頻道="發送公告的頻道", 內容="公告內容")
@app_commands.checks.has_permissions(administrator=True)
async def 發布公告(interaction: discord.Interaction, 頻道: discord.TextChannel, 內容: str):
    try:
        announcement_embed = discord.Embed(title="📣 伺服器公告", description=內容, color=discord.Color.gold(), timestamp=datetime.now())
        announcement_embed.set_footer(text=f"發布者: {interaction.user.name}")
        await 頻道.send("@everyone", embed=announcement_embed)
        await interaction.response.send_message(f"✅ 公告已成功發送到 {頻道.mention}。", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"❌ 我沒有權限在 {頻道.mention} 發送訊息。", ephemeral=True)

@bot.tree.command(name='禁言', description="禁言某位用戶指定分鐘。")
@app_commands.describe(用戶="要禁言的用戶", 分鐘="禁言的分鐘數 (1-40320)", 理由="禁言理由 (可選)")
@app_commands.checks.has_permissions(moderate_members=True)
async def 禁言(interaction: discord.Interaction, 用戶: discord.Member, 分鐘: app_commands.Range[int, 1, 40320], 理由: str = "無理由"):
    try:
        duration = discord.utils.utcnow() + timedelta(minutes=分鐘)
        await 用戶.timeout(duration, reason=理由)
        await interaction.response.send_message(f"✅ 已成功禁言 {用戶.mention} **{分鐘} 分鐘**。理由: {理由}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ 我沒有足夠權限禁言這位用戶，或者該用戶權限比我高。", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ 禁言時發生錯誤: {e}", ephemeral=True)


@bot.tree.command(name='用戶資料查詢', description="查詢用戶的詳細資料。")
@app_commands.describe(用戶="要查詢的用戶 (可選)")
async def 用戶資料查詢(interaction: discord.Interaction, 用戶: Optional[discord.Member] = None):
    用戶 = 用戶 or interaction.user
    embed = discord.Embed(title=f"👤 {用戶.name} 的用戶資料", color=用戶.color if 用戶.color != discord.Color.default() else discord.Color.greyple(), timestamp=datetime.now())
    embed.set_thumbnail(url=用戶.display_avatar.url)
    embed.add_field(name="🆔 用戶 ID", value=用戶.id, inline=False)
    embed.add_field(name="📅 創建帳號於", value=用戶.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
    embed.add_field(name="🚪 加入伺服器於", value=用戶.joined_at.strftime("%Y-%m-%d %H:%M:%S") if 用戶.joined_at else "未知", inline=True)
    roles = [role.mention for role in 用戶.roles if role.name != "@everyone"]
    if roles:
        role_display = ' '.join(roles[:10])
        if len(roles) > 10:
            role_display += f' ... (+{len(roles)-10}個)'
        embed.add_field(name=f"🛡️ 角色 ({len(roles)})", value=role_display, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='發起投票', description="創建一個簡易投票。")
@app_commands.describe(
    問題="投票的主題",
    選項一="第一個選項", 
    選項二="第二個選項", 
    選項三="第三個選項 (可選)", 
    選項四="第四個選項 (可選)", 
    選項五="第五個選項 (可選)"
)
async def 發起投票(interaction: discord.Interaction, 問題: str, 選項一: str, 選項二: str, 選項三: str = None, 選項四: str = None, 選項五: str = None):
    options_raw = [選項一, 選項二, 選項三, 選項四, 選項五]
    options = [opt for opt in options_raw if opt is not None]

    if len(options) < 2:
         return await interaction.response.send_message("❌ 投票至少需要兩個選項。", ephemeral=True)
         
    emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
    
    poll_description = "\n".join([f"{emojis[i]} **{options[i]}**" for i in range(len(options))])
    
    poll_embed = discord.Embed(title=f"🗳️ {問題}", description=poll_description, color=discord.Color.purple())
    poll_embed.set_footer(text=f"由 {interaction.user.name} 發起")
    
    await interaction.response.send_message(embed=poll_embed)
    poll_message = await interaction.original_response()
    
    for i in range(len(options)):
        await poll_message.add_reaction(emojis[i])

@bot.tree.command(name='擲骰子', description='擲骰子遊戲。')
@app_commands.describe(格式="骰子記號，例如: 2d10 (擲兩個 10 面的骰子)")
async def 擲骰子(interaction: discord.Interaction, 格式: str = '1d6'):
    try:
        match = re.match(r'(\d+)d(\d+)', 格式.lower())
        if not match:
            raise ValueError("格式錯誤")

        num_dice = int(match.group(1))
        sides = int(match.group(2))
        
        if num_dice <= 0 or sides <= 0 or num_dice > 100 or sides > 1000:
            return await interaction.response.send_message("骰子數量 (1-100) 和面數 (1-1000) 必須合理。", ephemeral=True)
            
        results = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(results)
        
        await interaction.response.send_message(f"🎲 {interaction.user.mention} 擲出了 **{格式}**：\n結果: {', '.join(map(str, results))}\n總和: **{total}**")
        
    except Exception:
        await interaction.response.send_message("❌ 錯誤: 請使用 XdY 格式 (例如: 2d10)。", ephemeral=True)

@bot.tree.command(name='關閉客服單', description="關閉當前客服單頻道 (限工單創建者或客服/管理員)。")
async def 關閉客服單(interaction: discord.Interaction):
    if interaction.channel.category and interaction.channel.category.name == TICKET_CATEGORY_NAME:
        is_admin = interaction.user.guild_permissions.administrator
        settings = get_guild_settings(interaction.guild_id)
        
        is_ticket_handler = False
        ticket_role_id = settings.get('ticket_role_id')
        if ticket_role_id:
             is_ticket_handler = discord.utils.get(interaction.user.roles, id=ticket_role_id) is not None

        is_creator = False
        if interaction.channel.topic and interaction.channel.topic.isdigit():
             is_creator = interaction.user.id == int(interaction.channel.topic)
        
        if is_admin or is_ticket_handler or is_creator:
            await interaction.response.send_message("此客服單將在 5 秒後永久刪除...")
            await asyncio.sleep(5)
            try:
                 await interaction.channel.delete(reason="客服單已完成處理")
            except discord.Forbidden:
                 await interaction.followup.send("❌ 機器人沒有權限刪除此頻道。請手動刪除。", ephemeral=True)

        else:
            await interaction.response.send_message("❌ 您沒有權限關閉此客服單。", ephemeral=True)
    else:
        await interaction.response.send_message("❌ 此頻道不是客服單頻道。", ephemeral=True)

# --- Web 伺服器所需函數 ---
async def status_handler(request):
    """
    處理 /status 請求，返回機器人運行狀態
    """
    # 這裡可以加入更詳細的檢查，確保 Bot 已經登入
    return web.Response(text="Bot is running and healthy", status=200)

async def start_web_server():
    """
    啟動 AIOHTTP Web 伺服器並顯示公開網址提示
    """
    app = web.Application()
    # 將根路徑和 /status 路徑都設為狀態檢查
    app.router.add_get('/', status_handler) 
    app.router.add_get('/status', status_handler)
    
    # 從環境變數中獲取 PORT 和 HOST
    port = int(os.environ.get('PORT', 8080))
    host = os.environ.get('HOST', '0.0.0.0')

    # 嘗試從環境變數獲取公開網址 (託管平台自動生成)
    # 不同的託管平台使用不同的環境變數，這裡嘗試幾個常見的
    public_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME') 
    if not public_host:
        public_host = os.environ.get('WEBSITE_HOSTNAME') 
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    
    # 在終端機顯示網址資訊
    print(f"\n--- 🌐 Web 伺服器狀態 ---")
    print(f"✅ Web Server 正在內部監聽 {host}:{port}")
    if public_host:
        # 使用偵測到的公開網址
        print(f"🔗 公開網址 (可供所有人進入): https://{public_host}/")
        print(f"🔗 Uptime 監控路徑: https://{public_host}/status")
    else:
        # 如果無法偵測，提醒用戶自行查找
        print(f"⚠️ 無法自動偵測公開網址。請前往您的託管平台 (e.g., Railway/Replit) 儀表板查看。")
        print(f"  * 如果您在 **Railway**，網址在 'Domains' 頁籤。\n")
        print(f"  * 如果您在 **Replit**，網址在 'Webview' 預覽視窗頂部。\n")
    print("--------------------------\n")
    
    try:
        await site.start()
    except Exception as e:
        # Web 伺服器失敗不影響 Bot 主程序運行
        print(f"❌ Web 伺服器啟動失敗: {e}")

# --- 啟動機器人 ---

if TOKEN:
    # 確保所有必要的檔案都存在
    for filename in [SETTINGS_FILE, TOKEN_FILE, AI_KEY_FILE, CWA_KEY_FILE]:
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                 if filename == TOKEN_FILE:
                     print(f"請將您的 Discord Bot Token 貼入 {TOKEN_FILE} 檔案中。")
                 elif filename == AI_KEY_FILE:
                      print(f"請將您的 Google Gemini API Key 貼入 {AI_KEY_FILE} 檔案中。")
                 elif filename == CWA_KEY_FILE:
                       print(f"請將您的 CWA Open Data API Key 貼入 {CWA_KEY_FILE} 檔案中。")
                 pass

    # 檢查 TOKEN 是否已填入
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ 警告：TOKEN 為空。請在 token.txt 中填入 Bot Token。")
    else:
        print("🚀 正在啟動機器人...")
        bot.run(TOKEN)