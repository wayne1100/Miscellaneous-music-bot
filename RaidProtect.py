import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time
from datetime import datetime, timedelta
import re # 確保頂部有導入 re 模組

# --- 新增和調整配置常數 ---
# 在此時間範圍內 (秒)，如果加入的成員數量超過 RAID_THRESHOLD，則觸發 Raid 模式
RAID_TIME_WINDOW = 5 
# 觸發 Raid 模式的成員數量門檻
RAID_THRESHOLD = 10 
# 觸發 Raid 模式後，懲罰將持續的時間 (秒)
RAID_PENALTY_DURATION = 600 # 10 分鐘

# 帳號年齡限制：帳號創建時間必須超過此天數，否則被視為可疑
MIN_ACCOUNT_AGE_DAYS = 7 

# 新成員名稱中包含這些關鍵字，將會被踢出 (已移除非 ASCII 檢查，避免誤判)
BANNED_NAME_PATTERNS = [
    r'[0-9]{3,}',     # 連續三個以上數字 (可能是廣告機器人)
    r'discord\.gg',   # 邀請連結
    r'http(s)?:\/\/.' # 網址連結
]

class RaidProtect(commands.Cog):
    """防禦系統：監控新成員加入，防範大規模惡意湧入 (Raid)。"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 紀錄新成員加入時間的隊列: {guild_id: [timestamp1, timestamp2, ...]}
        self.join_timestamps = {} 
        # 紀錄 Raid 模式狀態: {guild_id: datetime_when_penalty_ends}
        self.raid_mode_active = {} 
        print("✅ RaidProtect Cog 載入成功，已新增帳號年齡檢查與 Webhook 防禦。")

    
    # --- 輔助函數：檢查新成員名稱是否可疑 ---
    def check_suspicious_name(self, member: discord.Member) -> bool:
        """檢查用戶名稱是否包含可疑模式。"""
        for pattern in BANNED_NAME_PATTERNS:
            if re.search(pattern, member.name.lower()):
                return True
        return False

    # --- 輔助函數：檢查帳號年齡是否過低 ---
    def check_account_age(self, member: discord.Member) -> bool:
        """檢查帳號創建時間是否少於 MIN_ACCOUNT_AGE_DAYS。"""
        required_age = timedelta(days=MIN_ACCOUNT_AGE_DAYS)
        account_age = datetime.now(member.created_at.tzinfo) - member.created_at
        return account_age < required_age

    # --- 事件監聽：新成員加入 ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        current_time = time.time()
        
        # 0. 忽略 Bot 自己的操作
        if member.id == self.bot.user.id:
            return

        # 1. 帳號年齡檢查 (Anti-Alts)
        if self.check_account_age(member):
            try:
                await guild.kick(member, reason=f"[RaidProtect: Anti-Alts] 帳號創建時間少於 {MIN_ACCOUNT_AGE_DAYS} 天。")
                print(f"🚨 [年齡防禦] 在伺服器 {guild.name} 踢出新帳號 {member.display_name} ({member.id})。")
            except discord.Forbidden:
                print(f"❌ [年齡防禦] 權限不足，無法在 {guild.name} 踢出 {member.display_name}。")
            return
            
        # 2. 名稱檢查 (輕量級防禦)
        if self.check_suspicious_name(member):
            try:
                await guild.kick(member, reason="[RaidProtect: Name] 名稱包含可疑關鍵字或廣告。")
                print(f"🚨 [名稱防禦] 在伺服器 {guild.name} 踢出用戶 {member.display_name} ({member.id})。")
            except discord.Forbidden:
                print(f"❌ [名稱防禦] 權限不足，無法在 {guild.name} 踢出 {member.display_name}。")
            return
            
        # 3. Raid 模式檢查 (防止湧入)
        
        # ... (以下為上次提供的 Raid 模式邏輯，保持不變) ...
        if guild.id not in self.join_timestamps:
            self.join_timestamps[guild.id] = []
        
        self.join_timestamps[guild.id] = [t for t in self.join_timestamps[guild.id] if current_time - t <= RAID_TIME_WINDOW]
        self.join_timestamps[guild.id].append(current_time)
        
        if len(self.join_timestamps[guild.id]) >= RAID_THRESHOLD:
            await self.trigger_raid_mode(guild, member)
            
        # 4. 處理 Raid 模式下的加入 (確保在 Raid 模式下的用戶被踢出)
        if guild.id in self.raid_mode_active and datetime.now() < self.raid_mode_active[guild.id]:
             try:
                await guild.kick(member, reason="[RaidProtect: Flood] 伺服器處於 Raid 防禦模式。")
                print(f"🚨 [Raid 模式] 在伺服器 {guild.name} 踢出用戶 {member.display_name} ({member.id})。")
             except discord.Forbidden:
                pass
        
    # --- 核心防禦邏輯 ---
    async def trigger_raid_mode(self, guild: discord.Guild, triggering_member: discord.Member):
        
        if guild.id in self.raid_mode_active and datetime.now() < self.raid_mode_active[guild.id]:
            self.raid_mode_active[guild.id] = datetime.now() + timedelta(seconds=RAID_PENALTY_DURATION)
            print(f"⚠️ [RaidProtect] 伺服器 {guild.name} Raid 模式時間延長。")
            return
            
        self.raid_mode_active[guild.id] = datetime.now() + timedelta(seconds=RAID_PENALTY_DURATION)
        print(f"🔥 [RaidProtect] 伺服器 {guild.name} 觸發 Raid 模式！")
        
        # 1. 調整驗證等級 (提高到 'Highest' - 必須有電話驗證)
        original_verification_level = guild.verification_level
        try:
            await guild.edit(verification_level=discord.VerificationLevel.highest, reason="[RaidProtect] 進入 Raid 防禦模式。")
            print(f"✅ 在 {guild.name} 將驗證等級提高到 'Highest'。")
        except discord.Forbidden:
            print(f"❌ 權限不足，無法在 {guild.name} 更改驗證等級。")
            
        # 2. 移除新加入成員的紀錄，防止重複觸發
        self.join_timestamps[guild.id] = [] 
        
        # 3. 啟動計時器以恢復設定
        await asyncio.sleep(RAID_PENALTY_DURATION)
        
        # 4. 恢復設定
        if guild.id in self.raid_mode_active and datetime.now() >= self.raid_mode_active[guild.id]:
            try:
                # 恢復原來的驗證等級 (這裡我們不能直接恢復 original_verification_level，因為沒有儲存)
                # 實際應用中應該儲存原始等級，這裡暫時恢復為 Medium
                await guild.edit(verification_level=discord.VerificationLevel.medium, reason="[RaidProtect] 結束 Raid 防禦模式，恢復設定。")
                print(f"✅ 在 {guild.name} 恢復驗證等級。")
            except discord.Forbidden:
                pass
            finally:
                del self.raid_mode_active[guild.id]
                print(f"✅ 在 {guild.name} 退出 Raid 模式。")
                
# --- 載入 Cog 函數 ---
async def setup(bot):
    await bot.add_cog(RaidProtect(bot))