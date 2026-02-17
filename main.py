import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import aiosqlite
from datetime import datetime, timedelta
import random
import math

# ================== ТВОИ ID ==================
GUILD_ID = 1422153897362849905
ARCHIVE_CHANNEL_ID = 1473352413053190188

ROLES = {
    "admin": 1473348779888349377,
    "mod": 1473348724745961675,
    "support": 1473349102422196314,
}

# ================== НАСТРОЙКИ БОТА ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"✅ Синхронизировано на сервер {GUILD_ID}")

bot = MyBot()

# ================== СЛОВАРИ ==================
voice_tracking = {}

# ================== БАЗА ДАННЫХ ==================
async def init_db():
    async with aiosqlite.connect('warns.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                moderator_id INTEGER,
                guild_id INTEGER,
                reason TEXT,
                date TIMESTAMP,
                expired BOOLEAN DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                user_id INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS coins (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS voice_time (
                user_id INTEGER PRIMARY KEY,
                total_minutes INTEGER DEFAULT 0,
                last_join TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS coin_notifications (
                user_id INTEGER PRIMARY KEY,
                last_notification REAL DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS marriages (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER,
                married_since TIMESTAMP
            )
        ''')
        await db.commit()

async def check_expired_warns():
    await bot.wait_until_ready()
    while not bot.is_closed():
        seven_days_ago = datetime.now() - timedelta(days=7)
        async with aiosqlite.connect('warns.db') as db:
            await db.execute('UPDATE warns SET expired = 1 WHERE date < ? AND expired = 0', (seven_days_ago,))
            await db.commit()
        await asyncio.sleep(3600)

# ================== УВЕДОМЛЕНИЯ ==================
async def check_coin_milestone(user_id, db):
    cursor = await db.execute('SELECT balance FROM coins WHERE user_id = ?', (user_id,))
    row = await cursor.fetchone()
    if not row:
        return
    
    balance = row[0]
    cursor = await db.execute('SELECT last_notification FROM coin_notifications WHERE user_id = ?', (user_id,))
    row = await cursor.fetchone()
    last_notified = row[0] if row else 0
    
    current_milestone = int(balance // 100) * 100
    last_milestone = int(last_notified // 100) * 100
    
    if current_milestone > last_milestone:
        user = bot.get_user(user_id)
        if user:
            embed = discord.Embed(
                title="💰 Достижение!",
                description=f"Ты накопил **{int(current_milestone)} монет**! Так держать!",
                color=discord.Color.gold()
            )
            try:
                await user.send(embed=embed)
            except:
                pass
        
        await db.execute('INSERT INTO coin_notifications (user_id, last_notification) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET last_notification = ?',
                        (user_id, balance, balance))
        await db.commit()

# ================== ГОЛОС ==================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    if before.channel is None and after.channel is not None:
        voice_tracking[member.id] = (after.channel.id, datetime.now())
    
    elif before.channel is not None and after.channel is None:
        if member.id in voice_tracking:
            join_time = voice_tracking[member.id][1]
            minutes_spent = int((datetime.now() - join_time).total_seconds() / 60)
            
            if minutes_spent > 0:
                async with aiosqlite.connect('warns.db') as db:
                    await db.execute('INSERT INTO coins (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?',
                                    (member.id, minutes_spent, minutes_spent))
                    await db.execute('INSERT INTO voice_time (user_id, total_minutes) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_minutes = total_minutes + ?',
                                    (member.id, minutes_spent, minutes_spent))
                    await db.commit()
                    await check_coin_milestone(member.id, db)
            
            del voice_tracking[member.id]

# ================== СООБЩЕНИЯ ==================
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    async with aiosqlite.connect('warns.db') as db:
        word_count = len(message.content.split())
        
        if word_count >= 5:
            coins_earned = 0.05
            await db.execute('INSERT INTO coins (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?',
                            (message.author.id, coins_earned, coins_earned))
            await check_coin_milestone(message.author.id, db)
        
        await db.execute('INSERT INTO messages (user_id, count) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET count = count + 1',
                        (message.author.id,))
        await db.commit()
    
    await bot.process_commands(message)

# ================== КОМАНДЫ ==================
@bot.tree.command(name="help", description="Показать все команды")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 Команды бота",
        description="Все доступные команды",
        color=discord.Color.blue()
    )
    embed.add_field(name="👤 Обычные", 
                   value="`/help` — это меню\n`/ping` — задержка\n`/rules` — правила\n`/admins` — админы\n`/stat` — статистика\n`/top` — топ игроков\n`/marry` — брак", 
                   inline=False)
    embed.add_field(name="🛡️ Модерация", 
                   value="`/clear` — очистка\n`/warn` — предупреждение\n`/infoplayer` — инфо об игроке", 
                   inline=False)
    embed.add_field(name="🔨 Админ", 
                   value="`/ban` — бан\n`/kick` — кик\n`/ticket` — тикеты", 
                   inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Проверка задержки")
async def ping_command(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 **Понг!** Задержка: `{round(bot.latency * 1000)} мс`", ephemeral=True)

@bot.tree.command(name="rules", description="Правила сервера")
async def rules_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Правила сервера", color=discord.Color.red())
    embed.add_field(name="1️⃣ Уважение", value="• Относитесь к другим с уважением\n• Запрещены оскорбления", inline=False)
    embed.add_field(name="2️⃣ Контент", value="• 18+ запрещён\n• Спам запрещён", inline=False)
    embed.add_field(name="3️⃣ Администрация", value="• Выполняйте требования администрации", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="admins", description="Список администрации")
async def admins_command(interaction: discord.Interaction):
    admin_ids = [ROLES["admin"], ROLES["mod"]]
    admins = []
    for member in interaction.guild.members:
        if any(role.id in admin_ids for role in member.roles):
            admins.append(f"• {member.mention} — {member.top_role.name}")
    
    embed = discord.Embed(
        title="👮 Администрация сервера",
        description="\n".join(admins) if admins else "Нет администрации",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clear", description="Очистить сообщения")
@app_commands.describe(amount="Количество (1-100)")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def clear_command(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ Укажи число от 1 до 100", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Удалено **{len(deleted)}** сообщений", ephemeral=True)

@bot.tree.command(name="ban", description="Забанить пользователя")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"])
async def ban_command(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя забанить пользователя с равной или выше ролью", ephemeral=True)
    
    await member.ban(reason=reason)
    embed = discord.Embed(title="🔨 Бан", color=discord.Color.red())
    embed.add_field(name="Пользователь", value=member.mention)
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="kick", description="Выгнать пользователя")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"])
async def kick_command(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя кикнуть пользователя с равной или выше ролью", ephemeral=True)
    
    await member.kick(reason=reason)
    embed = discord.Embed(title="👢 Кик", color=discord.Color.orange())
    embed.add_field(name="Пользователь", value=member.mention)
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="warn", description="Выдать предупреждение")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def warn_command(interaction: discord.Interaction, member: discord.Member, reason: str):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя выдать варн пользователю с равной или выше ролью", ephemeral=True)
    
    async with aiosqlite.connect('warns.db') as db:
        await db.execute('INSERT INTO warns (user_id, moderator_id, guild_id, reason, date) VALUES (?, ?, ?, ?, ?)',
                        (member.id, interaction.user.id, interaction.guild_id, reason, datetime.now()))
        await db.commit()
        
        seven_days_ago = datetime.now() - timedelta(days=7)
        async with db.execute('SELECT COUNT(*) FROM warns WHERE user_id = ? AND guild_id = ? AND date > ? AND expired = 0',
                              (member.id, interaction.guild_id, seven_days_ago)) as cursor:
            warn_count = (await cursor.fetchone())[0]
    
    embed = discord.Embed(title="⚠️ Предупреждение", color=discord.Color.orange())
    embed.add_field(name="Пользователь", value=member.mention)
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    embed.add_field(name="Всего варнов", value=f"{warn_count}/5")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    if warn_count >= 5:
        await member.ban(reason="Автоматический бан: 5 предупреждений")
        await interaction.followup.send(embed=discord.Embed(title="🔨 Автобан", description=f"{member.mention} забанен за 5 варнов", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="infoplayer", description="Информация об игроке")
@app_commands.describe(member="Пользователь")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def infoplayer_command(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect('warns.db') as db:
        msg = await db.execute('SELECT count FROM messages WHERE user_id = ?', (member.id,))
        msg_count = (await msg.fetchone() or [0])[0]
        
        seven = datetime.now() - timedelta(days=7)
        active = await db.execute('SELECT reason, date, moderator_id FROM warns WHERE user_id = ? AND guild_id = ? AND date > ? AND expired = 0 ORDER BY date DESC', 
                                 (member.id, interaction.guild_id, seven))
        active_warns = await active.fetchall()
        
        total = await db.execute('SELECT COUNT(*) FROM warns WHERE user_id = ? AND guild_id = ?', (member.id, interaction.guild_id))
        total_warns = (await total.fetchone())[0]
        
        coin = await db.execute('SELECT balance FROM coins WHERE user_id = ?', (member.id,))
        coin_data = await coin.fetchone()
        coins = coin_data[0] if coin_data else 0

    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    
    embed = discord.Embed(title=f"📊 Информация о {member.display_name}", color=member.color)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="🆔 ID", value=member.id, inline=True)
    embed.add_field(name="🪙 Монеты", value=int(coins), inline=True)
    embed.add_field(name="💬 Сообщений", value=msg_count, inline=True)
    embed.add_field(name="⚠️ Варны", value=f"{len(active_warns)} активных / {total_warns} всего", inline=False)
    embed.add_field(name=f"🎭 Роли [{len(roles)}]", value=" ".join(roles) if roles else "Нет ролей", inline=False)

    if active_warns:
        warns_text = ""
        for r, d, mid in active_warns[:5]:
            mod = interaction.guild.get_member(mid)
            mod_name = mod.display_name if mod else "Неизвестно"
            date_str = datetime.fromisoformat(d).strftime("%d.%m.%Y")
            warns_text += f"• **{r}** — {mod_name} ({date_str})\n"
        embed.add_field(name="📋 Последние варны", value=warns_text, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== КРАСИВЫЙ /stat ==================
@bot.tree.command(name="stat", description="Показать статистику игрока")
@app_commands.describe(member="Пользователь (оставь пустым для себя)")
async def stat_command(interaction: discord.Interaction, member: discord.Member = None):
    if member is None:
        member = interaction.user
    
    async with aiosqlite.connect('warns.db') as db:
        # Сообщения
        msg_cursor = await db.execute('SELECT count FROM messages WHERE user_id = ?', (member.id,))
        msg_data = await msg_cursor.fetchone()
        msg_count = msg_data[0] if msg_data else 0
        
        # Монеты
        coin_cursor = await db.execute('SELECT balance FROM coins WHERE user_id = ?', (member.id,))
        coin_data = await coin_cursor.fetchone()
        coins = coin_data[0] if coin_data else 0
        
        # Варны
        seven_days_ago = datetime.now() - timedelta(days=7)
        warn_cursor = await db.execute('SELECT COUNT(*) FROM warns WHERE user_id = ? AND guild_id = ? AND date > ? AND expired = 0',
                                       (member.id, interaction.guild_id, seven_days_ago))
        warns = (await warn_cursor.fetchone())[0]
        
        # Топ позиция по монетам
        all_users = await db.execute('SELECT user_id, balance FROM coins ORDER BY balance DESC')
        rows = await all_users.fetchall()
        position = 1
        found = False
        for row in rows:
            if row[0] == member.id:
                found = True
                break
            position += 1
        
        if not found:
            count_cursor = await db.execute('SELECT COUNT(*) FROM coins')
            total_users = (await count_cursor.fetchone())[0]
            position = total_users + 1
        
        # Голос
        voice_cursor = await db.execute('SELECT total_minutes FROM voice_time WHERE user_id = ?', (member.id,))
        voice_data = await voice_cursor.fetchone()
        voice_minutes = voice_data[0] if voice_data else 0
        
        # Пара
        marry_cursor = await db.execute('SELECT partner_id FROM marriages WHERE user_id = ?', (member.id,))
        marry_data = await marry_cursor.fetchone()
        partner_name = "Нет"
        if marry_data:
            partner = interaction.guild.get_member(marry_data[0])
            if partner:
                partner_name = partner.mention
    
    # Уровень и прогресс
    level = max(1, int(math.sqrt(coins / 100))) if coins > 0 else 1
    next_level_coins = (level + 1) ** 2 * 100
    coins_to_next = max(0, next_level_coins - coins)
    
    # Прогресс-бар
    progress = int((coins / next_level_coins) * 10)
    progress_bar = "🟩" * progress + "⬜" * (10 - progress)
    
    # Статус
    status_emoji = {
        discord.Status.online: "🟢",
        discord.Status.idle: "🟡",
        discord.Status.dnd: "🔴",
        discord.Status.offline: "⚫"
    }.get(member.status, "⚫")
    
    status_text = {
        discord.Status.online: "Онлайн",
        discord.Status.idle: "Неактивен",
        discord.Status.dnd: "Не беспокоить",
        discord.Status.offline: "Не в сети"
    }.get(member.status, "Не в сети")
    
    # Создаём красивый embed
    embed = discord.Embed(
        title=f"⭐ Статистика {member.display_name}",
        description=f"{status_emoji} **{status_text}**",
        color=member.color if member.color != discord.Color.default() else discord.Color.blue()
    )
    
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    
    # Основные показатели
    embed.add_field(name="💍 Пара", value=partner_name, inline=True)
    embed.add_field(name="⚠️ Варны", value=f"{'🔴' if warns > 0 else '🟢'} {warns}/5", inline=True)
    embed.add_field(name="🏆 Топ", value=f"#{position}", inline=True)
    
    # Монеты и уровень
    embed.add_field(name="🪙 Монеты", value=f"**{int(coins)}**", inline=True)
    embed.add_field(name="🎚️ Уровень", value=f"**{level}**", inline=True)
    embed.add_field(name="📈 До уровня", value=f"{int(coins_to_next)} монет", inline=True)
    
    # Прогресс-бар
    embed.add_field(name="✨ Прогресс", value=f"{progress_bar} `{int(coins)}/{int(next_level_coins)}`", inline=False)
    
    # Активность
    embed.add_field(name="💬 Сообщения", value=f"**{msg_count}**", inline=True)
    embed.add_field(name="🎤 В голосе", value=f"**{voice_minutes}** мин", inline=True)
    
    embed.set_footer(text=f"Запросил: {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="top", description="Топ игроков по монетам")
async def top_command(interaction: discord.Interaction):
    async with aiosqlite.connect('warns.db') as db:
        cursor = await db.execute('SELECT user_id, balance FROM coins ORDER BY balance DESC LIMIT 10')
        rows = await cursor.fetchall()
    
    if not rows:
        await interaction.response.send_message("❌ Пока нет данных для топа", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🏆 Топ игроков по монетам",
        description="Самые богатые участники сервера",
        color=discord.Color.gold()
    )
    
    medals = ["🥇", "🥈", "🥉", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹"]
    
    for i, (user_id, balance) in enumerate(rows, 1):
        user = interaction.guild.get_member(user_id)
        name = user.display_name if user else f"Неизвестный"
        medal = medals[i-1]
        embed.add_field(
            name=f"{medal} {i}. {name}",
            value=f"🪙 **{int(balance)}** монет",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="marry", description="Предложить пожениться")
@app_commands.describe(partner="Пользователь, которому предлагаешь")
async def marry_command(interaction: discord.Interaction, partner: discord.Member):
    if partner.id == interaction.user.id:
        return await interaction.response.send_message("❌ Нельзя жениться на себе", ephemeral=True)
    
    if partner.bot:
        return await interaction.response.send_message("❌ Нельзя жениться на боте", ephemeral=True)
    
    async with aiosqlite.connect('warns.db') as db:
        for uid in [interaction.user.id, partner.id]:
            cursor = await db.execute('SELECT partner_id FROM marriages WHERE user_id = ?', (uid,))
            if await cursor.fetchone():
                return await interaction.response.send_message(f"❌ {interaction.user.mention if uid == interaction.user.id else partner.mention} уже в браке", ephemeral=True)
    
    class MarryView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="✅ Согласиться", style=discord.ButtonStyle.green)
        async def accept(self, interaction2: discord.Interaction, button: discord.ui.Button):
            if interaction2.user.id != partner.id:
                return await interaction2.response.send_message("❌ Только партнёр может согласиться", ephemeral=True)
            
            async with aiosqlite.connect('warns.db') as db:
                now = datetime.now()
                await db.execute('INSERT INTO marriages (user_id, partner_id, married_since) VALUES (?, ?, ?)',
                                (interaction.user.id, partner.id, now))
                await db.execute('INSERT INTO marriages (user_id, partner_id, married_since) VALUES (?, ?, ?)',
                                (partner.id, interaction.user.id, now))
                await db.commit()
            
            embed = discord.Embed(
                title="💍 Поздравляем!",
                description=f"{interaction.user.mention} и {partner.mention} теперь в браке!",
                color=discord.Color.pink()
            )
            await interaction.edit_original_response(embed=embed, view=None)
        
        @discord.ui.button(label="❌ Отказаться", style=discord.ButtonStyle.red)
        async def decline(self, interaction2: discord.Interaction, button: discord.ui.Button):
            if interaction2.user.id != partner.id:
                return await interaction2.response.send_message("❌ Только партнёр может отказаться", ephemeral=True)
            
            await interaction.edit_original_response(content="❌ Предложение отклонено", embed=None, view=None)
    
    embed = discord.Embed(
        title="💍 Предложение брака",
        description=f"{interaction.user.mention} предлагает {partner.mention} вступить в брак!",
        color=discord.Color.purple()
    )
    
    await interaction.response.send_message(embed=embed, view=MarryView())

# ================== ТИКЕТЫ ==================
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Открыть тикет", style=discord.ButtonStyle.green)
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for ch in interaction.guild.channels:
            if ch.name == f"ticket-{interaction.user.name.lower()}":
                return await interaction.response.send_message("❌ У тебя уже есть открытый тикет", ephemeral=True)
        
        category = discord.utils.get(interaction.guild.categories, name="ТИКЕТЫ")
        if not category:
            category = await interaction.guild.create_category("ТИКЕТЫ")
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ROLES["support"]): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ROLES["admin"]): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )
        
        await interaction.response.send_message(f"✅ Тикет создан: {channel.mention}", ephemeral=True)
        
        embed = discord.Embed(
            title="📩 Новый тикет",
            description=f"Тикет открыл {interaction.user.mention}\nОпиши свою проблему",
            color=discord.Color.green()
        )
        
        await channel.send(embed=embed, view=TicketCloseView())

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📦 Архивация тикета...", ephemeral=True)
        
        messages = []
        async for msg in interaction.channel.history(limit=100, oldest_first=True):
            if not msg.author.bot:
                time_str = msg.created_at.strftime("%d.%m.%Y %H:%M")
                messages.append(f"[{time_str}] {msg.author.display_name}: {msg.content}")
        
        closer = interaction.user
        role_names = ", ".join([r.name for r in closer.roles if r.name != "@everyone"]) or "Нет ролей"
        
        archive_embed = discord.Embed(
            title=f"📦 Архив тикета: {interaction.channel.name}",
            color=discord.Color.dark_gray(),
            timestamp=datetime.now()
        )
        archive_embed.add_field(name="👤 Закрыл", value=f"{closer.mention} (`{closer.id}`)", inline=True)
        archive_embed.add_field(name="🎭 Роли", value=role_names, inline=True)
        archive_embed.add_field(name="💬 Сообщений", value=len(messages), inline=True)
        
        archive_channel = interaction.guild.get_channel(ARCHIVE_CHANNEL_ID)
        if archive_channel:
            await archive_channel.send(embed=archive_embed)
            if messages:
                history_text = "\n".join(messages)
                if len(history_text) > 1900:
                    for i in range(0, len(history_text), 1900):
                        await archive_channel.send(f"```{history_text[i:i+1900]}```")
                else:
                    await archive_channel.send(f"```{history_text}```")
        
        await interaction.channel.delete()

@bot.tree.command(name="ticket", description="Создать панель тикетов")
@app_commands.checks.has_any_role(ROLES["admin"])
async def ticket_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Система поддержки",
        description="Нажми на кнопку ниже, чтобы открыть тикет",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=TicketView())

# ================== ЗАПУСК ==================
@bot.event
async def on_ready():
    await init_db()
    bot.loop.create_task(check_expired_warns())
    print(f"✅ {bot.user} готов! Серверов: {len(bot.guilds)}")
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())

bot.run(os.getenv('BOT_TOKEN'))
