import discord
from discord.ext import commands
import discord.app_commands
import wavelink
import asyncio
import re 
from typing import Optional, List
import random 

# ====================================================================
# --- 配置區：確保這些資訊與您的 Lavalink 伺服器完全匹配 ---
# ====================================================================
LAVALINK_HOST = '你的LAVALINK伺服器連線IP' 
LAVALINK_PORT = 你的LAVALINK伺服器連線埠
LAVALINK_PASSWORD = '' # 替換為您的 Lavalink 密碼
LAVALINK_SECURE = False 
UPDATE_INTERVAL_SECONDS = 1 # 進度條每秒更新一次
IDLE_TIMEOUT_SECONDS = 120 # 閒置斷開時間：2 分鐘

# --- 自定義表情符號 ID (進度條) --- 請勿更改
BAR_START_EMPTY = "▬" # 左邊框-未完成
BAR_MIDDLE_EMPTY = "▬" # 中間段-未完成
BAR_END_EMPTY = "▬" # 右邊框-未完成
BAR_START_FILLED = "<:imagesremovebgpreview:1444516369461673984>" # 左邊框-已完成
BAR_MIDDLE_FILLED = "<:imagesremovebgpreview:1444516369461673984>" # 中間段-已完成
BAR_END_FILLED = "<:imagesremovebgpreview:1444516369461673984>" # 右邊框-已完成
# -----------------------------------


# 隨機播放的預設關鍵字列表 (已更新為流行中文歌)
RANDOM_PLAY_QUERIES = [
    "scsearch:最新流行中文歌",
    "scsearch:華語流行金曲",
    "scsearch:中文排行榜歌曲",
    "scsearch:周杰倫 熱門歌曲", 
]
# ====================================================================

# 定義自訂的 Wavelink 播放器
class CustomPlayer(wavelink.Player):
    """自訂的 Wavelink 播放器，用於管理佇列和狀態。"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = wavelink.Queue()
        self.autoplay = wavelink.AutoPlayMode.disabled 
        self.last_message = None
        self.update_task = None
        self.idle_timer_task = None # 閒置計時器任務

# -----------------------------------------------------------
# --- 輔助函式：時間格式化與進度條生成 (已根據 ID 和長度要求修改) ---
# -----------------------------------------------------------
def format_time(ms: int) -> str:
    """將毫秒轉換為 HH:MM:SS 格式。"""
    seconds = ms // 1000
    minutes = seconds // 60
    hours = minutes // 60
    
    if hours > 0:
        return f"{hours:02}:{minutes % 60:02}:{seconds % 60:02}"
    return f"{minutes % 60:02}:{seconds % 60:02}"

def create_progress_bar(position_ms: int, length_ms: int, bar_length: int = 10) -> str:
    """創建音樂進度條，使用自定義表情符號且無指示器。
    
    bar_length 設置為 5 (中間段的數量)，總長度為 7 (頭 + 5 中 + 尾)。
    """
    if length_ms == 0 or length_ms is None:
        return f"Live: {format_time(position_ms)}"

    ratio = position_ms / length_ms
    ratio = max(0, min(ratio, 1))

    # 計算已完成的區塊數量 (佔總長度 bar_length=5)
    blocks_filled = int(ratio * bar_length)
    blocks_empty = bar_length - blocks_filled

    # 確保區塊數量正確
    blocks_filled = max(0, min(blocks_filled, bar_length))
    blocks_empty = bar_length - blocks_filled


    # 1. 左邊框
    if blocks_filled > 0:
        # 只要有進度，左邊框就使用 :bar2_1:
        bar_start = BAR_START_FILLED
    else:
        # 0% 進度
        bar_start = BAR_START_EMPTY

    # 2. 中間段落
    filled_middle = BAR_MIDDLE_FILLED * blocks_filled
    empty_middle = BAR_MIDDLE_EMPTY * blocks_empty
    
    # 組合中間段
    middle_string = filled_middle + empty_middle
    
    # 3. 右邊框
    if blocks_filled == bar_length:
        # 100% 完成
        bar_end = BAR_END_FILLED
    else:
        # 未完成
        bar_end = BAR_END_EMPTY
        
    # 最終組合
    bar_string = bar_start + middle_string + bar_end

    current_time = format_time(position_ms)
    total_time = format_time(length_ms)
    
    return f"`{current_time}` **{bar_string}** `{total_time}`"

# -----------------------------------------------------------
# --- SelectTrackView 類別：歌曲選擇選單 (未修改) ---
# -----------------------------------------------------------
class SelectTrackView(discord.ui.View):
    """用於展示關鍵字搜尋結果並讓使用者選擇的 View。"""
    def __init__(self, bot: commands.Bot, tracks: List[wavelink.Playable]):
        super().__init__(timeout=60) 
        self.bot = bot
        self.tracks = tracks
        self.add_item(self.create_select())

    def create_select(self):
        """創建下拉選單選項。"""
        options = []
        for i, track in enumerate(self.tracks):
            label = f"{i+1}. {track.title}"[:100]
            description = f"來自 {track.author} ({format_time(track.length)})"[:100]
            options.append(discord.SelectOption(
                label=label,
                description=description,
                value=str(i) 
            ))

        select = discord.ui.Select(
            placeholder="請選擇要播放的歌曲...",
            options=options,
            row=0
        )
        select.callback = self.select_callback
        return select

    async def select_callback(self, interaction: discord.Interaction):
        """處理使用者選擇歌曲後的動作。"""
        await interaction.response.defer()

        selected_index = int(interaction.data['values'][0])
        track = self.tracks[selected_index]
        
        player: CustomPlayer = interaction.guild.voice_client
        
        if not player or not player.connected:
            await interaction.followup.edit_message(
                interaction.message.id, 
                content="❌ 機器人已斷開連線，請重新使用 `/音樂系統-播放音樂`。", 
                embed=None, 
                view=None
            )
            self.stop()
            return
            
        music_cog = self.bot.get_cog("MusicLavalink")
        if music_cog:
            await music_cog.start_or_queue_track(interaction, player, track, interaction.message)
            
        self.stop()
        
    async def on_timeout(self):
        """選單超時時，自動清除訊息。"""
        try:
            await self.message.edit(content="⏳ 歌曲選擇已超時。", embed=None, view=None)
        except:
            pass 

    @discord.ui.button(label="❌ 取消選擇", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消歌曲選擇。", embed=None, view=None)
        self.stop()


# -----------------------------------------------------------
# --- MusicControlView 類別：控制面板按鈕邏輯 (未修改) ---
# -----------------------------------------------------------
class MusicControlView(discord.ui.View):
    """音樂控制面板的按鈕介面。"""
    def __init__(self, bot: commands.Bot, vc: CustomPlayer):
        super().__init__(timeout=None)
        self.bot = bot
        self.vc = vc
        self.music_cog = bot.get_cog("MusicLavalink") 

    async def update_view(self):
        """根據播放器狀態更新按鈕外觀 (主要更新音量顯示)。"""
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "show_volume":
                item.label = f"🔊 {self.vc.volume}%"

    # 播放/暫停按鈕 (Row 0)
    @discord.ui.button(label="⏯️ 暫停/播放", style=discord.ButtonStyle.primary, custom_id="pause_play", row=0)
    async def pause_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.vc.paused:
            await self.vc.resume()
            if self.vc.update_task is None:
                self.vc.update_task = self.bot.loop.create_task(self.music_cog.update_player_embed(self.vc))
        else:
            await self.vc.pause()
            if self.vc.update_task:
                 self.vc.update_task.cancel()
                 self.vc.update_task = None
        
        if self.vc.last_message:
            embed = self.vc.last_message.embeds[0]
            footer_text = embed.footer.text.split('|')[0].strip()
            embed.set_footer(text=f"{footer_text} | 狀態: {'播放中' if not self.vc.paused else '已暫停'}", icon_url=embed.footer.icon_url)
            await self.vc.last_message.edit(embed=embed, view=self)

    # 跳過按鈕 (Row 0)
    @discord.ui.button(label="⏭️ 跳過", style=discord.ButtonStyle.secondary, custom_id="skip", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.vc.stop() 
        
    # 停止/斷開按鈕 (Row 0)
    @discord.ui.button(label="⏹️ 停止/斷開", style=discord.ButtonStyle.danger, custom_id="stop_disconnect", row=0)
    async def stop_disconnect(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop() 
        
        if self.vc.last_message:
            await self.vc.last_message.edit(content="音樂播放已停止並斷開連線。", embed=None, view=None)
            self.vc.last_message = None
            
        if self.vc.update_task:
            self.vc.update_task.cancel()
            self.vc.update_task = None
        
        # 停止閒置計時器
        if self.vc.idle_timer_task:
            self.vc.idle_timer_task.cancel()
            self.vc.idle_timer_task = None
            
        await self.vc.disconnect()
            
    # 減小音量按鈕 (Row 1)
    @discord.ui.button(label="➖", style=discord.ButtonStyle.secondary, custom_id="volume_down", row=1)
    async def volume_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        new_volume = max(0, self.vc.volume - 10) 
        await self.vc.set_volume(new_volume)
        await self.update_view()
        if self.vc.last_message:
            await self.vc.last_message.edit(view=self)

    # 顯示音量按鈕 (Row 1)
    @discord.ui.button(label=f"🔊 100%", style=discord.ButtonStyle.blurple, custom_id="show_volume", row=1)
    async def show_volume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    # 增大音量按鈕 (Row 1)
    @discord.ui.button(label="➕", style=discord.ButtonStyle.secondary, custom_id="volume_up", row=1)
    async def volume_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        new_volume = min(100, self.vc.volume + 10) 
        await self.vc.set_volume(new_volume)
        await self.update_view()
        if self.vc.last_message:
            await self.vc.last_message.edit(view=self)
            
# -----------------------------------------------------------
# --- MusicLavalink 類別：Cog 核心邏輯 (未修改) ---
# -----------------------------------------------------------
class MusicLavalink(commands.Cog):
    """
    Lavalink 音樂播放 Cog (使用 Wavelink v2 語法)
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.loop.create_task(self.connect_nodes())

    # --- 閒置計時器邏輯 ---
    async def idle_timeout(self, player: CustomPlayer):
        """計時器到期後執行斷開連線。"""
        await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        
        # 再次檢查，以防在 sleep 期間有人加入/退出
        member_count = len([m for m in player.channel.members if not m.bot])
        
        if member_count == 0 and player.connected:
            if player.last_message:
                await player.last_message.edit(content="🕒 語音頻道閒置超過 2 分鐘，已自動斷開連線。", embed=None, view=None)
                player.last_message = None
            
            if player.update_task:
                player.update_task.cancel()
                player.update_task = None
                
            await player.disconnect()
            player.idle_timer_task = None
            
    def start_idle_timer(self, player: CustomPlayer):
        """啟動或重設閒置計時器。"""
        if player.idle_timer_task:
            player.idle_timer_task.cancel()
        
        # 只有在沒有使用者時才啟動計時器
        member_count = len([m for m in player.channel.members if not m.bot])
        if member_count == 0:
            player.idle_timer_task = self.bot.loop.create_task(self.idle_timeout(player))
        else:
            player.idle_timer_task = None # 有使用者，確保計時器為空

    # --- 語音狀態更新事件監聽 ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        player: CustomPlayer = member.guild.voice_client
        if not player or not player.connected:
            return

        # 處理使用者加入/退出機器人所在的語音頻道
        if before.channel != player.channel and after.channel == player.channel:
            # 有人加入機器人所在的頻道
            if player.idle_timer_task:
                player.idle_timer_task.cancel()
                player.idle_timer_task = None
        
        elif before.channel == player.channel and after.channel != player.channel:
            # 有人離開機器人所在的頻道
            member_count = len([m for m in player.channel.members if not m.bot])
            if member_count == 0:
                self.start_idle_timer(player) # 啟動閒置計時器

    # --- 定時更新 Embed 的任務 ---
    async def update_player_embed(self, player: CustomPlayer):
        """每隔 1 秒更新一次播放訊息的 Embed。"""
        while True:
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
            
            if not player.connected or player.paused or player.update_task is None:
                return 

            try:
                if player.last_message and player.current:
                    embed = self._create_now_playing_embed(player.current, player.guild.icon, 
                                                            position_ms=player.position, paused=player.paused)
                    
                    view = MusicControlView(self.bot, player)
                    await view.update_view()

                    await player.last_message.edit(embed=embed, view=view)

            except discord.NotFound:
                player.last_message = None
                if player.update_task:
                    player.update_task.cancel()
                    player.update_task = None
                return
            except Exception as e:
                if player.update_task:
                    player.update_task.cancel()
                    player.update_task = None
                print(f"❌ 更新播放頁面錯誤: {e}")
                
    # --- Wavelink 連接及事件處理 ---

    async def connect_nodes(self):
        await self.bot.wait_until_ready()
        
        protocol = "ws"
        uri = f'{protocol}://{LAVALINK_HOST}:{LAVALINK_PORT}'

        node: wavelink.Node = wavelink.Node(
            uri=uri, 
            password=LAVALINK_PASSWORD,
        )
        try:
            await wavelink.Pool.connect(nodes=[node], client=self.bot)
        except Exception as e:
            print(f"❌ 無法連接 Lavalink 節點。錯誤: {e}")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"✅ Lavalink 節點已連接並準備就緒: {payload.node.uri}")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player: CustomPlayer = payload.player
        
        if player.update_task:
            player.update_task.cancel()
            player.update_task = None
            
        # 播放結束時，檢查閒置計時器
        member_count = len([m for m in player.channel.members if not m.bot])
        if member_count == 0:
            self.start_idle_timer(player)
            # 如果沒有使用者，直接等待閒置計時器處理，不進行隨機播放
            return

        if not player.queue.is_empty:
            # 佇列中有下一首歌，播放
            next_track = player.queue.get()
            await player.play(next_track)
            
            player.update_task = self.bot.loop.create_task(self.update_player_embed(player))

            if player.last_message:
                embed = self._create_now_playing_embed(next_track, player.channel.guild.icon, position_ms=0)
                view = MusicControlView(self.bot, player)
                await view.update_view() 
                await player.last_message.edit(embed=embed, view=view)
        else:
            # 佇列為空，隨機播放歌曲 (流行中文歌)
            try:
                random_query = random.choice(RANDOM_PLAY_QUERIES)
                tracks = await wavelink.Pool.fetch_tracks(random_query)

                if tracks and not isinstance(tracks, wavelink.Playlist):
                    random_track = random.choice(tracks)
                    await player.play(random_track)
                    
                    player.update_task = self.bot.loop.create_task(self.update_player_embed(player))

                    if player.last_message:
                        embed = self._create_now_playing_embed(random_track, player.channel.guild.icon, position_ms=0)
                        view = MusicControlView(self.bot, player)
                        await view.update_view() 
                        await player.last_message.edit(embed=embed, view=view)
                        
                else:
                    # 隨機查詢失敗，閒置 60 秒後斷開 (如果閒置計時器未啟動)
                    await self._disconnect_after_timeout_if_playing(player)
            except Exception as e:
                print(f"❌ 隨機播放失敗: {e}")
                await self._disconnect_after_timeout_if_playing(player)

    async def _disconnect_after_timeout_if_playing(self, player: CustomPlayer):
        """在播放結束/隨機播放失敗後，等待 60 秒後斷開連線 (如果閒置計時器未啟動)。"""
        if player.idle_timer_task:
            return # 已經有閒置計時器在處理，不重複處理

        await asyncio.sleep(60) 
        if player.connected and player.queue.is_empty and not player.paused and not player.playing:
             if player.last_message:
                await player.last_message.edit(content="機器人閒置過久，已自動斷開連線。", embed=None, view=None)
                player.last_message = None
             await player.disconnect()
                    
    # --- 實用函式 ---
    
    def _create_now_playing_embed(self, track: wavelink.Playable, icon_url: str, position_ms: int = 0, paused: bool = False) -> discord.Embed:
        """建立帶有進度條的當前播放訊息的 Embed。"""
        embed = discord.Embed(
            title="🎶 正在播放",
            description=f"[{track.title}]({track.uri})",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=getattr(track, 'thumbnail', None))
        
        embed.add_field(
            name="進度", 
            value=create_progress_bar(position_ms, track.length) if track.length > 0 else "直播中...", 
            inline=False
        )
        
        status = '已暫停' if paused else '播放中'
        embed.set_footer(text=f"來源: {track.author} | 狀態: {status}", icon_url=icon_url)
        return embed

    async def _ensure_voice(self, interaction: discord.Interaction, player: CustomPlayer):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ 請先加入語音頻道！", ephemeral=True)
            return None
        
        newly_connected = False
        if not player or not player.connected:
            player = await interaction.user.voice.channel.connect(cls=CustomPlayer)
            newly_connected = True
        elif player.channel.id != interaction.user.voice.channel.id:
             await player.move_to(interaction.user.voice.channel)
             
        # 如果是新連接，啟動閒置計時器，檢查當前頻道內人數
        if newly_connected or player.idle_timer_task: 
            self.start_idle_timer(player)
        
        return player

    # 歌曲播放/入佇列的核心邏輯
    async def start_or_queue_track(self, interaction: discord.Interaction, player: CustomPlayer, track: wavelink.Playable, msg_to_edit: Optional[discord.Message] = None):
        """開始播放新歌曲或將其加入佇列。"""
        is_playing_before = player.playing
        
        # 確保有使用者在頻道內，否則不重設/取消計時器，讓閒置計時器自行處理
        member_count = len([m for m in player.channel.members if not m.bot])
        if member_count > 0 and player.idle_timer_task:
            player.idle_timer_task.cancel()
            player.idle_timer_task = None
        
        if is_playing_before:
            player.queue.put(track)
            content = f"✅ 已將 `{track.title}` 加入佇列。"
            if msg_to_edit:
                await msg_to_edit.edit(content=content, embed=None, view=None)
            else:
                await interaction.edit_original_response(content=content, embed=None)
        else:
            await player.play(track)
            
            if player.update_task is None:
                player.update_task = self.bot.loop.create_task(self.update_player_embed(player))

            embed = self._create_now_playing_embed(track, interaction.guild.icon, position_ms=0)
            view = MusicControlView(self.bot, player)
            await view.update_view()

            if msg_to_edit:
                msg = await msg_to_edit.edit(content="", embed=embed, view=view)
            else:
                msg = await interaction.edit_original_response(embed=embed, view=view)
                
            player.last_message = msg 

    # --- 應用程式指令 ---

    @discord.app_commands.command(name="音樂系統-播放音樂", description="在語音頻道中播放音樂")
    @discord.app_commands.describe(search="歌曲連結或關鍵字")
    async def play(self, interaction: discord.Interaction, search: str):
        if not interaction.guild:
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        player = interaction.guild.voice_client
        
        player = await self._ensure_voice(interaction, player)
        if not player:
            return

        is_url = re.match(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', search)
        
        if is_url:
            query = search
        else:
            query = f'scsearch:{search}'
            
        tracks = await wavelink.Pool.fetch_tracks(query)

        if not tracks:
            await interaction.edit_original_response(content=f"❌ 找不到與 `{search}` 相關的結果。", embed=None)
            return

        
        if isinstance(tracks, wavelink.Playlist):
            player.queue.extend(tracks.tracks)
            first_track = tracks.tracks[0]
            
            is_playing_before = player.playing
            
            if not is_playing_before:
                await self.start_or_queue_track(interaction, player, first_track)
                await interaction.channel.send(f"✅ 已將播放列表 `{tracks.name}` ({len(tracks.tracks)} 首歌) 加入佇列，並開始播放。", delete_after=15)
            else:
                await interaction.edit_original_response(content=f"✅ 已將播放列表 `{tracks.name}` ({len(tracks.tracks)} 首歌) 加入佇列。", embed=None)

        elif not is_url and len(tracks) > 1:
            top_10_tracks = tracks[:10]
            view = SelectTrackView(self.bot, top_10_tracks)
            
            embed = discord.Embed(
                title="🔍 歌曲選擇",
                description=f"請在下方選單中選擇 **`{search}`** 的搜尋結果:",
                color=discord.Color.gold()
            )
            
            msg = await interaction.edit_original_response(embed=embed, view=view)
            view.message = msg 

        else:
            track = tracks[0]
            await self.start_or_queue_track(interaction, player, track)

    
    # --- /加入佇列 指令 ---
    @discord.app_commands.command(name="音樂系統-加入佇列", description="將單首歌曲加入當前播放佇列。")
    @discord.app_commands.describe(search="歌曲名稱或連結")
    async def add_to_queue(self, interaction: discord.Interaction, search: str):
        if not interaction.guild:
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        player: CustomPlayer = interaction.guild.voice_client
        if not player or not player.connected:
             await interaction.edit_original_response(content="❌ 機器人沒有連接語音頻道。請先使用 `/播放` 指令。", embed=None)
             return

        is_url = re.match(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', search)
        query = search if is_url else f'scsearch:{search}'
        
        tracks = await wavelink.Pool.fetch_tracks(query)

        if not tracks or isinstance(tracks, wavelink.Playlist):
            await interaction.edit_original_response(content=f"❌ 找不到單首歌曲 `{search}`。如果想新增播放列表，請使用 `/新增播放列表`。", embed=None)
            return

        track = tracks[0]
        player.queue.put(track)
        
        await interaction.edit_original_response(
            content=f"✅ 歌曲 `{track.title}` 已加入佇列。佇列中還有 {player.queue.count} 首歌。", 
            embed=None
        )


    # --- /新增播放列表 指令 ---
    @discord.app_commands.command(name="音樂系統-新增播放列表", description="將一個播放列表的連結加入佇列")
    @discord.app_commands.describe(url="播放列表的 URL 連結")
    async def add_playlist(self, interaction: discord.Interaction, url: str):
        if not interaction.guild:
            await interaction.response.send_message("❌ 此指令僅限在伺服器中使用。", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        player: CustomPlayer = interaction.guild.voice_client
        if not player or not player.connected:
             await interaction.edit_original_response(content="❌ 請先使用 `/播放` 指令讓機器人加入語音頻道。", embed=None)
             return

        tracks = await wavelink.Pool.fetch_tracks(url)

        if not tracks or not isinstance(tracks, wavelink.Playlist):
            await interaction.edit_original_response(content="❌ 找不到播放列表，或提供的連結不是有效的播放列表。", embed=None)
            return
        
        player.queue.extend(tracks.tracks)
        
        await interaction.edit_original_response(
            content=f"✅ 成功將播放列表 **{tracks.name}** ({len(tracks.tracks)} 首歌) 加入佇列。", 
            embed=None
        )

    # --- 暫停、繼續、斷開、佇列指令 ---
        
    @discord.app_commands.command(name="音樂系統-暫停撥放", description="暫停正在播放的歌曲")
    async def pause(self, interaction: discord.Interaction):
        player: CustomPlayer = interaction.guild.voice_client
        if not player or not player.playing:
            await interaction.response.send_message("❌ 沒有正在播放的歌曲。", ephemeral=True)
            return
            
        await player.pause(True)
        if player.update_task:
            player.update_task.cancel()
            player.update_task = None
            
        await interaction.response.send_message("⏸️ 歌曲已暫停。", ephemeral=True)
        
    @discord.app_commands.command(name="音樂系統-繼續撥放", description="繼續播放暫停的歌曲")
    async def resume(self, interaction: discord.Interaction):
        player: CustomPlayer = interaction.guild.voice_client
        if not player or not player.paused:
            await interaction.response.send_message("❌ 歌曲沒有被暫停。", ephemeral=True)
            return
            
        await player.pause(False)
        if player.update_task is None:
            player.update_task = self.bot.loop.create_task(self.update_player_embed(player))
            
        await interaction.response.send_message("▶️ 歌曲已繼續播放。", ephemeral=True)
        
    @discord.app_commands.command(name="音樂系統-斷開連接", description="停止播放並斷開語音連線")
    async def disconnect(self, interaction: discord.Interaction):
        player: CustomPlayer = interaction.guild.voice_client
        if not player or not player.connected:
            await interaction.response.send_message("❌ 機器人沒有連接語音頻道。", ephemeral=True)
            return
            
        if player.update_task:
            player.update_task.cancel()
            player.update_task = None
            
        if player.idle_timer_task:
            player.idle_timer_task.cancel()
            player.idle_timer_task = None
            
        if player.last_message:
            await player.last_message.edit(content="已斷開語音連線。", embed=None, view=None)
            player.last_message = None
            
        await player.disconnect()
        await interaction.response.send_message("✅ 已斷開語音連線。", ephemeral=True)
        
    @discord.app_commands.command(name="音樂系統-查看佇列", description="顯示當前歌曲佇列 (最多前10首)")
    async def queue_cmd(self, interaction: discord.Interaction):
        player: CustomPlayer = interaction.guild.voice_client
        if not player or (player.queue.is_empty and not player.current):
             await interaction.response.send_message("佇列中沒有歌曲。", ephemeral=True)
             return
        
        embed = discord.Embed(title="🎵 當前佇列", color=discord.Color.blue())
        
        current_track = player.current
        if current_track:
            queue_content = [f"**1. 正在播放：** {current_track.title} `{format_time(current_track.length)}`"]
        else:
            queue_content = []
            
        
        q = player.queue.copy()
        q_list = [f"**{i+2}.** {track.title} `{format_time(track.length)}`" for i, track in enumerate(q)][:9] 
        
        queue_content.extend(q_list)
        
        remaining_count = player.queue.count - 9
        if remaining_count > 0:
             queue_content.append(f"...\n**還有 {remaining_count} 首歌**")
             
        embed.description = "\n".join(queue_content)
             
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None: # 👈 確保這行頂著最左邊
    await bot.add_cog(MusicLavalink(bot))
    # 👈 這行應該只有 4 個空格的標準縮排