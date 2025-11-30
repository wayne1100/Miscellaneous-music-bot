import discord
from discord.ext import commands
from discord import app_commands
import json
import datetime
import asyncio
from typing import Optional

# --- 設定部分 ---
BLACKLIST_FILE = 'global_blacklist.json'
HISTORY_FILE = 'gban_history.json'

# --- 資料處理函數 ---
# 這些函數需要從 GlobalBan 類別中分離出來，作為輔助函數

def load_blacklist():
    """從 JSON 檔案載入黑名單數據。"""
    try:
        with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        print(f"警告：{BLACKLIST_FILE} 檔案內容無效，已創建空黑名單。")
        return {}

def save_blacklist(data):
    """將黑名單數據儲存到 JSON 檔案。"""
    with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_history():
    """從 JSON 檔案載入操作紀錄。"""
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def log_action(log_entry):
    """將操作紀錄新增到歷史紀錄檔案。"""
    history_data = load_history()
    history_data.append(log_entry)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, indent=4, ensure_ascii=False)

# -----------------------------------------------------------
# --- GlobalBan Cog 核心邏輯 (已轉換為斜線指令) ---
# -----------------------------------------------------------

class GlobalBan(commands.Cog):
    """全域黑名單管理系統 Cog"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.global_blacklist = load_blacklist()
        print(f'✅ GlobalBan Cog 載入成功，目前全域黑名單中有 {len(self.global_blacklist)} 位用戶。')

    # --- 事件監聽 (用於自動封鎖新加入的黑名單用戶) ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """當新成員加入伺服器時，檢查是否在全域黑名單中，並自動封鎖。"""
        user_id_str = str(member.id)
        
        # 由於是事件，我們需要隨時檢查最新的黑名單
        self.global_blacklist = load_blacklist()

        if user_id_str in self.global_blacklist:
            reason = self.global_blacklist[user_id_str].get('reason', '未提供原因')
            print(f'🚨 黑名單用戶加入: {member.name} ({user_id_str})，執行自動封鎖。')
            
            try:
                await member.guild.ban(member, reason=f"[全域黑名單自動封鎖] 原因: {reason}")
                
            except discord.Forbidden:
                print(f'❌ 權限不足，無法在伺服器 {member.guild.name} 中封鎖用戶 {member.name}。')
            except Exception as e:
                print(f'自動封鎖時發生錯誤: {e}')

    # --- 斜線指令群組 ---
    global_ban_group = app_commands.Group(name="gban", description="全域黑名單管理系統")

    @global_ban_group.command(name='ban', description='[管理員指令] 將指定 ID 加入全域黑名單。')
    @app_commands.describe(user_id='要封鎖的用戶ID', reason='封鎖原因')
    @app_commands.default_permissions(administrator=True)
    async def global_ban_cmd(self, interaction: discord.Interaction, user_id: str, reason: str = "未提供原因"):
        """
        將用戶 ID 加入全域黑名單，並在執行伺服器內同步封鎖所有黑名單用戶。
        """
        
        try:
            user_id_int = int(user_id)
        except ValueError:
            await interaction.response.send_message("❌ 用戶ID格式無效，請確保它是一個純數字。", ephemeral=True)
            return
            
        await interaction.response.defer() # 預先回應，防止超時
        
        if user_id in self.global_blacklist:
            await interaction.followup.send(f'⚠️ 用戶 ID `{user_id}` 已經存在於黑名單中。')
            return

        # 1. 執行新增操作並儲存
        self.global_blacklist[user_id] = {
            'reason': reason,
            'added_by': str(interaction.user),
            'timestamp': str(datetime.datetime.now())
        }
        save_blacklist(self.global_blacklist)

        # 2. 執行紀錄與追蹤 (日誌)
        executor = interaction.user
        log_entry = {
            "timestamp": str(datetime.datetime.now()),
            "action": "gban_add",
            "command_used": f"/gban ban {user_id} {reason}",
            "target_id": user_id,
            "executor": {
                "id": str(executor.id),
                "username": executor.display_name,
                "full_tag": str(executor),
                "is_bot": executor.bot,
                "guild_id": str(interaction.guild_id) if interaction.guild_id else "DM"
            },
            "ban_reason": reason
        }
        log_action(log_entry)
        
        # 3. 創建 Embed 訊息 (美化回覆)
        embed_color = discord.Color.from_rgb(255, 0, 0) 
        current_time = datetime.datetime.now().strftime("%Y/%m/%d 下午 %H:%M")

        target_user = None
        try:
            target_user = await self.bot.fetch_user(user_id_int)
        except discord.NotFound:
            pass 

        embed = discord.Embed(color=embed_color)
        embed.set_author(name=f"全域黑名單系統 - 新增", icon_url=interaction.user.display_avatar.url)
        embed.description = "**全域封鎖**" 

        embed.add_field(name="目標", value=f"{target_user.name if target_user else '未知用戶'} ({user_id})", inline=False)
        embed.add_field(name="原因", value=reason, inline=False)

        embed.set_footer(text=f"操作時間: {current_time}")

        if target_user:
            embed.set_thumbnail(url=target_user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)
        
        # 4. 執行本地同步封鎖 (新功能)
        synced_count = 0
        
        # 遍歷當前伺服器的所有成員 (需要 Intents.members)
        if interaction.guild:
            # 確保我們有最新的黑名單 ID 集合
            blacklist_ids = set(self.global_blacklist.keys())
            
            for member in interaction.guild.members:
                member_id_str = str(member.id)
                
                if member_id_str in blacklist_ids and member.id != self.bot.user.id:
                    try:
                        ban_reason = self.global_blacklist[member_id_str].get('reason', '未提供原因')
                        await interaction.guild.ban(member, reason=f"[全域黑名單同步封鎖] 原因: {ban_reason}")
                        synced_count += 1
                    except Exception:
                        pass # 忽略權限不足或其他錯誤

            sync_msg = f"🔨 **本地同步完成：** 已在伺服器 `{interaction.guild.name}` 封鎖了 **{synced_count}** 位存在於全域黑名單中的用戶（包括剛才的目標用戶）。"
        else:
            sync_msg = "ℹ️ 此指令無法在私訊中執行本地同步。"

        await interaction.followup.send(sync_msg)


    @global_ban_group.command(name='unban', description='[管理員指令] 從黑名單中移除指定 ID。')
    @app_commands.describe(user_id='要解除封鎖的用戶ID')
    @app_commands.default_permissions(administrator=True)
    async def global_unban_cmd(self, interaction: discord.Interaction, user_id: str):
        """將用戶 ID 從全域黑名單中移除，並以 Embed 方式呈現。"""
        
        try:
            user_id_int = int(user_id)
        except ValueError:
            await interaction.response.send_message("❌ 用戶ID格式無效，請確保它是一個純數字。", ephemeral=True)
            return
            
        await interaction.response.defer() 
        
        if user_id not in self.global_blacklist:
            await interaction.followup.send(f'⚠️ 用戶 ID `{user_id}` 不在黑名單中。')
            return

        # 執行移除操作
        del self.global_blacklist[user_id]
        save_blacklist(self.global_blacklist)

        # 記錄操作
        log_entry = {
            "timestamp": str(datetime.datetime.now()),
            "action": "gban_remove",
            "command_used": f"/gban unban {user_id}",
            "target_id": user_id,
            "executor": {
                "id": str(interaction.user.id),
                "full_tag": str(interaction.user),
            },
        }
        log_action(log_entry)

        # 創建 Embed 訊息
        embed_color = discord.Color.green() 
        current_time = datetime.datetime.now().strftime("%Y/%m/%d 下午 %H:%M")

        target_user = None
        try:
            target_user = await self.bot.fetch_user(user_id_int)
        except discord.NotFound:
            pass

        embed = discord.Embed(title="全域黑名單系統 - 解除", description="**全域解除封鎖**", color=embed_color)
        embed.set_author(name=f"操作者: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="目標用戶 ID", value=user_id, inline=True)
        embed.add_field(name="目標用戶名稱", value=f"{target_user.name if target_user else '未知用戶'}", inline=True)
        embed.set_footer(text=f"操作時間: {current_time}")

        await interaction.followup.send(embed=embed)
        
        # 嘗試在本伺服器解除封鎖
        if interaction.guild:
            try:
                await interaction.guild.unban(discord.Object(id=user_id_int))
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法解除本地封鎖。")
                pass

    @global_ban_group.command(name='sync', description='[管理員指令] 手動在當前伺服器同步封鎖所有黑名單中的成員。')
    @app_commands.default_permissions(administrator=True)
    async def global_sync_cmd(self, interaction: discord.Interaction):
        """手動掃描並在當前伺服器封鎖所有已存在於全域黑名單中的成員。"""
        
        if not interaction.guild:
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return

        await interaction.response.defer()
        
        self.global_blacklist = load_blacklist()
        blacklist_ids = set(self.global_blacklist.keys())
        synced_count = 0
        
        await interaction.followup.send("🔍 **開始本地同步：** 正在掃描伺服器中所有已列入全域黑名單的用戶...")
        
        for member in interaction.guild.members:
            member_id_str = str(member.id)
            
            if member_id_str in blacklist_ids and member.id != self.bot.user.id:
                try:
                    ban_reason = self.global_blacklist[member_id_str].get('reason', '未提供原因')
                    await interaction.guild.ban(member, reason=f"[全域黑名單手動同步封鎖] 原因: {ban_reason}")
                    synced_count += 1
                except Exception:
                    continue
        
        if synced_count > 0:
            await interaction.followup.send(
                f"✅ **同步完成！** 伺服器 `{interaction.guild.name}` 成功封鎖了 **{synced_count}** 位存在於全域黑名單中的用戶。"
            )
        else:
            await interaction.followup.send(
                f"ℹ️ **同步完成！** 伺服器 `{interaction.guild.name}` 中沒有發現需要封鎖的全域黑名單用戶。"
            )

    @global_ban_group.command(name='history', description='[管理員指令] 查詢指定 ID 的黑名單歷史紀錄。')
    @app_commands.describe(user_id='要查詢的用戶ID')
    @app_commands.default_permissions(administrator=True)
    async def global_history_cmd(self, interaction: discord.Interaction, user_id: str):
        """查詢指定用戶 ID 的所有黑名單操作紀錄。"""
        
        await interaction.response.defer(ephemeral=True) 
        
        history_data = load_history()
        related_logs = [
            log for log in history_data if log.get('target_id') == user_id
        ]
        
        if not related_logs:
            await interaction.followup.send(f'ℹ️ 找不到用戶 ID `{user_id}` 的黑名單操作紀錄。', ephemeral=True)
            return

        embed = discord.Embed(title=f"用戶 {user_id} 的黑名單歷史", color=discord.Color.blue())
        
        for i, log in enumerate(related_logs, 1):
            action = "✅ 加入黑名單" if log['action'] == "gban_add" else "❌ 解除黑名單" if log['action'] == "gban_remove" else "❓ 未知操作"
            reason = log.get('ban_reason', '無')
            executor_name = log['executor']['full_tag']
            timestamp = log['timestamp'].split('.')[0]
            command_used = log.get('command_used', 'N/A')

            field_value = (
                f'**時間:** {timestamp}\n'
                f'**執行者:** {executor_name} ({log["executor"]["id"]})\n'
                f'**原因:** {reason}\n'
                f'**指令:** `{command_used}`'
            )
            embed.add_field(name=f"{i}. {action}", value=field_value, inline=False)
            
        await interaction.followup.send(embed=embed, ephemeral=True)

    @global_ban_group.command(name='list', description='[管理員指令] 顯示所有全域黑名單中的用戶。')
    @app_commands.default_permissions(administrator=True)
    async def global_list_cmd(self, interaction: discord.Interaction):
        """讀取並顯示所有全域黑名單中的用戶 ID。"""

        await interaction.response.defer()
        
        self.global_blacklist = load_blacklist()
        
        if not self.global_blacklist:
            await interaction.followup.send("ℹ️ 目前全域黑名單為空。")
            return

        entries = []
        
        # 為了效能，只做一次 gather
        user_ids_to_fetch = [int(uid) for uid in self.global_blacklist.keys()]
        users = await asyncio.gather(*[self.bot.fetch_user(uid) for uid in user_ids_to_fetch], return_exceptions=True)
        
        user_map = {str(u.id): u for u in users if isinstance(u, discord.User)}
        
        for user_id, data in self.global_blacklist.items():
            user_obj = user_map.get(user_id)
            
            # 格式化顯示名稱 (實現提及 + ID 的效果)
            if user_obj:
                display_name = f"<@{user_id}> ({user_id})"
            else:
                display_name = f"@未知用戶 ({user_id})"
            
            reason = data.get('reason', '無')
            added_by = data.get('added_by', '未知')
            timestamp = data.get('timestamp', '未知')
            
            # 列表項目的格式
            entry = (
                f"• **{display_name}**\n"
                f"  > 原因: {reason}\n"
                f"  > 新增者: {added_by} ({timestamp.split('.')[0]})\n"
            )
            entries.append(entry)
            
        
        # 設置分頁邏輯
        current_content = ""
        embeds_content = []
        MAX_LENGTH = 3800 # Embed description max is 4096. 3800 is safer.

        for entry in entries:
            if len(current_content) + len(entry) > MAX_LENGTH:
                embeds_content.append(current_content)
                current_content = entry
            else:
                current_content += entry
                
        if current_content:
            embeds_content.append(current_content)

        total_pages = len(embeds_content)
        
        # 發送所有分頁的 Embed 訊息
        for i, content in enumerate(embeds_content, 1):
            list_embed = discord.Embed(
                title="🌐 全域黑名單列表",
                description=f"**全域黑名單 ({len(self.global_blacklist)} 人)**\n\n{content}",
                color=discord.Color.from_rgb(47, 49, 54) 
            )
            list_embed.set_footer(text=f"第 {i}/{total_pages} 頁 | 使用 /gban list 查詢所有黑名單用戶")
            await interaction.followup.send(embed=list_embed)


async def setup(bot):
    """機器人載入 Cog 時調用。"""
    # 🚨 修正：將類別名稱 GlobalBan 傳入 add_cog
    await bot.add_cog(GlobalBan(bot))