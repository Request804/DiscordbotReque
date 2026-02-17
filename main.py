import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import asyncpg
from datetime import datetime, timedelta
import math
import aiohttp  # Для нейросети

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
        self.db_pool = None

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"✅ Синхронизировано на сервер {GUILD_ID}")

bot = MyBot()

# ================== СЛОВАРИ ==================
voice_tracking = {}
user_conversations = {}  # Для истории диалогов с нейросетью

# ================== ТОКЕН ДЛЯ НЕЙРОСЕТИ ==================
AI_TOKEN = os.getenv('AI_TOKEN')  # Получаем из переменных окружения

# ================== ФУНКЦИЯ ОЖИДАНИЯ БД ==================
async def wait_for_db():
    """Ждём, пока база данных инициализируется"""
    while bot.db_pool is None:
        await asyncio.sleep(1)
    return bot.db_pool

# ================== БАЗА ДАННЫХ (PostgreSQL) ==================
async def init_db():
    """Инициализация подключения к PostgreSQL и создание таблиц"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ ОШИБКА: DATABASE_URL не найден в переменных окружения!")
        return
    
    bot.db_pool = await asyncpg.create_pool(database_url)
    
    async with bot.db_pool.acquire() as conn:
        # Варны
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS warns (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                guild_id BIGINT,
                moderator_id BIGINT,
                reason TEXT,
                date TIMESTAMP,
                expired BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Сообщения
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                user_id BIGINT,
                guild_id BIGINT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # Монеты
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS coins (
                user_id BIGINT,
                guild_id BIGINT,
                balance REAL DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # XP
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS xp (
                user_id BIGINT,
                guild_id BIGINT,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # Голосовое время
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS voice_time (
                user_id BIGINT,
                guild_id BIGINT,
                total_minutes INTEGER DEFAULT 0,
                last_join TIMESTAMP,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        # Уведомления
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS coin_notifications (
                user_id BIGINT PRIMARY KEY,
                last_notification REAL DEFAULT 0
            )
        ''')
        
        # Браки
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS marriages (
                user_id BIGINT,
                guild_id BIGINT,
                partner_id BIGINT,
                married_since TIMESTAMP,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
    
    print("✅ PostgreSQL подключён и таблицы созданы")

async def check_expired_warns():
    await bot.wait_until_ready()
    while not bot.is_closed():
        seven_days_ago = datetime.now() - timedelta(days=7)
        async with bot.db_pool.acquire() as conn:
            await conn.execute('UPDATE warns SET expired = TRUE WHERE date < $1 AND expired = FALSE', seven_days_ago)
        await asyncio.sleep(3600)

async def check_coin_milestone(user_id, conn):
    row = await conn.fetchrow('SELECT balance FROM coins WHERE user_id = $1', user_id)
    if not row:
        return
    
    balance = row['balance']
    
    row = await conn.fetchrow('SELECT last_notification FROM coin_notifications WHERE user_id = $1', user_id)
    last_notified = row['last_notification'] if row else 0
    
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
        
        await conn.execute('''
            INSERT INTO coin_notifications (user_id, last_notification) 
            VALUES ($1, $2) 
            ON CONFLICT (user_id) DO UPDATE SET last_notification = $2
        ''', user_id, balance)

async def add_xp(user_id, guild_id, amount, conn):
    row = await conn.fetchrow('SELECT xp, level FROM xp WHERE user_id = $1 AND guild_id = $2', user_id, guild_id)
    
    if row:
        xp, level = row['xp'], row['level']
        xp += amount
        
        next_level_xp = level * 100
        
        while xp >= next_level_xp:
            level += 1
            xp -= next_level_xp
            next_level_xp = level * 100
        
        await conn.execute('UPDATE xp SET xp = $1, level = $2 WHERE user_id = $3 AND guild_id = $4', 
                          xp, level, user_id, guild_id)
    else:
        await conn.execute('INSERT INTO xp (user_id, guild_id, xp, level) VALUES ($1, $2, $3, $4)', 
                          user_id, guild_id, amount, 1)

# ================== ПРИВЕТСТВИЕ ПРИ ДОБАВЛЕНИИ НА СЕРВЕР ==================
@bot.event
async def on_guild_join(guild):
    print(f"✅ Бот добавлен на новый сервер: {guild.name} (ID: {guild.id})")
    
    if guild.system_channel:
        embed = discord.Embed(
            title="👋 Спасибо что добавили меня!",
            description="Я бот с экономикой, варнами, уровнями, тикетами и нейросетью!\n"
                       "У каждого сервера своя независимая экономика.\n"
                       "Используй `/help` чтобы увидеть все команды.",
            color=discord.Color.green()
        )
        embed.add_field(name="🤖 Нейросеть", value="`/ai` — поговори с искусственным интеллектом", inline=False)
        embed.add_field(name="📊 Статистика", value="За сообщения и войс ты получаешь XP и монеты", inline=False)
        embed.add_field(name="🛡️ Модерация", value="Варны, баны, кики, тайм-ауты", inline=False)
        embed.add_field(name="💍 Социальное", value="Браки и топ игроков", inline=False)
        try:
            await guild.system_channel.send(embed=embed)
        except:
            pass

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
                pool = await wait_for_db()
                async with pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO coins (user_id, guild_id, balance) VALUES ($1, $2, $3) 
                        ON CONFLICT (user_id, guild_id) DO UPDATE SET balance = coins.balance + $3
                    ''', member.id, member.guild.id, minutes_spent)
                    
                    await add_xp(member.id, member.guild.id, minutes_spent * 5, conn)
                    
                    await conn.execute('''
                        INSERT INTO voice_time (user_id, guild_id, total_minutes) VALUES ($1, $2, $3) 
                        ON CONFLICT (user_id, guild_id) DO UPDATE SET total_minutes = voice_time.total_minutes + $3
                    ''', member.id, member.guild.id, minutes_spent)
                    
                    await check_coin_milestone(member.id, conn)
            
            del voice_tracking[member.id]

# ================== СООБЩЕНИЯ ==================
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    
    pool = await wait_for_db()
    async with pool.acquire() as conn:
        word_count = len(message.content.split())
        if word_count >= 5:
            coins_earned = 0.05
            await conn.execute('''
                INSERT INTO coins (user_id, guild_id, balance) VALUES ($1, $2, $3) 
                ON CONFLICT (user_id, guild_id) DO UPDATE SET balance = coins.balance + $3
            ''', message.author.id, message.guild.id, coins_earned)
            await check_coin_milestone(message.author.id, conn)
        
        await add_xp(message.author.id, message.guild.id, 1, conn)
        
        await conn.execute('''
            INSERT INTO messages (user_id, guild_id, count) VALUES ($1, $2, 1) 
            ON CONFLICT (user_id, guild_id) DO UPDATE SET count = messages.count + 1
        ''', message.author.id, message.guild.id)
    
    await bot.process_commands(message)

# ================== КОМАНДЫ ==================
@bot.tree.command(name="help", description="Показать все команды")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📚 Команды", color=discord.Color.blue())
    embed.add_field(name="🤖 Нейросеть", value="`/ai` — поговори с искусственным интеллектом", inline=False)
    embed.add_field(name="👤 Обычные", value="`/ping` `/admins` `/stat` `/top` `/marry`", inline=False)
    embed.add_field(name="🛡️ Модерация", value="`/clear` `/warn` `/infoplayer`", inline=False)
    embed.add_field(name="🔨 Админ", value="`/ban` `/kick` `/ticket`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Проверка задержки")
async def ping_command(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Понг! Задержка: {round(bot.latency * 1000)} мс", ephemeral=True)

@bot.tree.command(name="admins", description="Список администрации")
async def admins_command(interaction: discord.Interaction):
    admin_ids = [ROLES["admin"], ROLES["mod"]]
    admins = [f"• {m.mention} — {m.top_role.name}" for m in interaction.guild.members if any(r.id in admin_ids for r in m.roles)]
    await interaction.response.send_message(embed=discord.Embed(title="👮 Администрация", description="\n".join(admins) or "Нет", color=discord.Color.gold()), ephemeral=True)

@bot.tree.command(name="clear", description="Очистить сообщения")
@app_commands.describe(amount="Количество (1-100)")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def clear_command(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ От 1 до 100", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Удалено {len(deleted)} сообщений", ephemeral=True)

@bot.tree.command(name="ban", description="Забанить пользователя")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"])
async def ban_command(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя забанить", ephemeral=True)
    await member.ban(reason=reason)
    await interaction.response.send_message(embed=discord.Embed(title="🔨 Бан", description=f"{member.mention} забанен", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="kick", description="Выгнать пользователя")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"])
async def kick_command(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя кикнуть", ephemeral=True)
    await member.kick(reason=reason)
    await interaction.response.send_message(embed=discord.Embed(title="👢 Кик", description=f"{member.mention} выгнан", color=discord.Color.orange()), ephemeral=True)

@bot.tree.command(name="warn", description="Выдать предупреждение")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def warn_command(interaction: discord.Interaction, member: discord.Member, reason: str):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя выдать варн", ephemeral=True)
    
    pool = await wait_for_db()
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO warns (user_id, guild_id, moderator_id, reason, date) VALUES ($1, $2, $3, $4, $5)',
                          member.id, interaction.guild_id, interaction.user.id, reason, datetime.now())
        
        seven_days_ago = datetime.now() - timedelta(days=7)
        row = await conn.fetchrow('SELECT COUNT(*) FROM warns WHERE user_id = $1 AND guild_id = $2 AND date > $3 AND expired = FALSE',
                                 member.id, interaction.guild_id, seven_days_ago)
        warn_count = row['count']
    
    embed = discord.Embed(title="⚠️ Предупреждение", color=discord.Color.orange())
    embed.add_field(name="Пользователь", value=member.mention)
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    embed.add_field(name="Всего варнов", value=f"{warn_count}/5")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    if warn_count >= 5:
        await member.ban(reason="Автобан: 5 предупреждений")
        await interaction.followup.send(embed=discord.Embed(title="🔨 Автобан", description=f"{member.mention} забанен за 5 варнов", color=discord.Color.red()), ephemeral=True)

# ================== /infoplayer С КНОПКАМИ ==================
class InfoplayerView(discord.ui.View):
    def __init__(self, member):
        super().__init__(timeout=60)
        self.member = member
    
    @discord.ui.button(label="🔨 Забанить", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("❌ Нельзя забанить", ephemeral=True)
        
        await self.member.ban(reason="Бан через инфоплейер")
        await interaction.response.send_message(f"✅ {self.member.mention} забанен", ephemeral=True)
    
    @discord.ui.button(label="👢 Кикнуть", style=discord.ButtonStyle.danger)
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("❌ Нельзя кикнуть", ephemeral=True)
        
        await self.member.kick(reason="Кик через инфоплейер")
        await interaction.response.send_message(f"✅ {self.member.mention} кикнут", ephemeral=True)
    
    @discord.ui.button(label="⏳ Тайм-аут", style=discord.ButtonStyle.secondary)
    async def timeout_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("❌ Нельзя дать тайм-аут", ephemeral=True)
        
        await self.member.timeout(timedelta(hours=1), reason="Тайм-аут через инфоплейер")
        await interaction.response.send_message(f"✅ {self.member.mention} в тайм-ауте на 1 час", ephemeral=True)
    
    @discord.ui.button(label="⚠️ Варн", style=discord.ButtonStyle.primary)
    async def warn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("❌ Нельзя выдать варн", ephemeral=True)
        
        pool = await wait_for_db()
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO warns (user_id, guild_id, moderator_id, reason, date) VALUES ($1, $2, $3, $4, $5)',
                              self.member.id, interaction.guild_id, interaction.user.id, "Варн через инфоплейер", datetime.now())
        
        await interaction.response.send_message(f"✅ {self.member.mention} получил варн", ephemeral=True)
    
    @discord.ui.button(label="📩 Тикет", style=discord.ButtonStyle.success)
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        category = discord.utils.get(interaction.guild.categories, name="ТИКЕТЫ")
        if not category:
            category = await interaction.guild.create_category("ТИКЕТЫ")
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            self.member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ROLES["support"]): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ROLES["admin"]): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{self.member.name}",
            category=category,
            overwrites=overwrites
        )
        
        await interaction.response.send_message(f"✅ Тикет создан: {channel.mention}", ephemeral=True)
        await channel.send(embed=discord.Embed(title="📩 Тикет", description=f"Тикет открыт для {self.member.mention}", color=discord.Color.green()), view=TicketCloseView())

@bot.tree.command(name="infoplayer", description="Информация об игроке (админ)")
@app_commands.describe(member="Пользователь")
@app_commands.checks.has_any_role(ROLES["admin"])
async def infoplayer_command(interaction: discord.Interaction, member: discord.Member):
    pool = await wait_for_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT count FROM messages WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        msg_count = row['count'] if row else 0
        
        seven = datetime.now() - timedelta(days=7)
        row = await conn.fetchrow('SELECT COUNT(*) FROM warns WHERE user_id = $1 AND guild_id = $2 AND date > $3 AND expired = FALSE',
                                 member.id, interaction.guild_id, seven)
        active_warns = row['count']
        
        row = await conn.fetchrow('SELECT COUNT(*) FROM warns WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        total_warns = row['count']
        
        row = await conn.fetchrow('SELECT balance FROM coins WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        coins = row['balance'] if row else 0
        
        row = await conn.fetchrow('SELECT xp, level FROM xp WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        xp, level = (row['xp'], row['level']) if row else (0, 1)
        
        row = await conn.fetchrow('SELECT total_minutes FROM voice_time WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        voice_minutes = row['total_minutes'] if row else 0
        
        row = await conn.fetchrow('SELECT partner_id FROM marriages WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        partner_name = "Нет"
        if row and row['partner_id']:
            partner = interaction.guild.get_member(row['partner_id'])
            if partner:
                partner_name = partner.mention
    
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    
    embed = discord.Embed(title=f"🔍 Инфоплейер: {member.display_name}", color=discord.Color.red())
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    
    embed.add_field(name="🆔 ID", value=member.id, inline=True)
    embed.add_field(name="📅 Создан", value=member.created_at.strftime("%d.%m.%Y"), inline=True)
    embed.add_field(name="📥 Присоединился", value=member.joined_at.strftime("%d.%m.%Y"), inline=True)
    
    embed.add_field(name="🪙 Монеты", value=int(coins), inline=True)
    embed.add_field(name="🎚️ Уровень", value=level, inline=True)
    embed.add_field(name="✨ XP", value=xp, inline=True)
    
    embed.add_field(name="💬 Сообщения", value=msg_count, inline=True)
    embed.add_field(name="🎤 В голосе", value=f"{voice_minutes} мин", inline=True)
    embed.add_field(name="⚠️ Варны", value=f"{active_warns} акт / {total_warns} всего", inline=True)
    
    embed.add_field(name="💍 Пара", value=partner_name, inline=True)
    embed.add_field(name=f"🎭 Роли [{len(roles)}]", value=" ".join(roles) if roles else "Нет ролей", inline=False)
    
    embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, view=InfoplayerView(member), ephemeral=True)

# ================== /stat ==================
@bot.tree.command(name="stat", description="Показать статистику игрока")
@app_commands.describe(member="Пользователь (оставь пустым для себя)")
async def stat_command(interaction: discord.Interaction, member: discord.Member = None):
    if member is None:
        member = interaction.user
    
    pool = await wait_for_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT count FROM messages WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        msg_count = row['count'] if row else 0
        
        row = await conn.fetchrow('SELECT balance FROM coins WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        coins = row['balance'] if row else 0
        
        row = await conn.fetchrow('SELECT xp, level FROM xp WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        if row:
            xp, level = row['xp'], row['level']
            next_level_xp = level * 100
        else:
            xp, level = 0, 1
            next_level_xp = 100
        
        seven_days_ago = datetime.now() - timedelta(days=7)
        row = await conn.fetchrow('SELECT COUNT(*) FROM warns WHERE user_id = $1 AND guild_id = $2 AND date > $3 AND expired = FALSE',
                                 member.id, interaction.guild_id, seven_days_ago)
        warns = row['count']
        
        rows = await conn.fetch('SELECT user_id FROM coins WHERE guild_id = $1 ORDER BY balance DESC', interaction.guild_id)
        position = 1
        found = False
        for i, row in enumerate(rows, 1):
            if row['user_id'] == member.id:
                position = i
                found = True
                break
        
        if not found:
            total = await conn.fetchval('SELECT COUNT(*) FROM coins WHERE guild_id = $1', interaction.guild_id)
            position = total + 1 if total else 1
        
        row = await conn.fetchrow('SELECT total_minutes FROM voice_time WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        voice_minutes = row['total_minutes'] if row else 0
        
        row = await conn.fetchrow('SELECT partner_id FROM marriages WHERE user_id = $1 AND guild_id = $2', member.id, interaction.guild_id)
        partner_name = "Нет"
        if row and row['partner_id']:
            partner = interaction.guild.get_member(row['partner_id'])
            if partner:
                partner_name = partner.mention
    
    progress = int((xp / next_level_xp) * 10)
    progress_bar = "🟩" * progress + "⬜" * (10 - progress)
    
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
    
    embed = discord.Embed(
        title=f"⭐ Статистика {member.display_name}",
        description=f"{status_emoji} **{status_text}**",
        color=member.color if member.color != discord.Color.default() else discord.Color.blue()
    )
    
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    
    embed.add_field(name="💍 Пара", value=partner_name, inline=True)
    embed.add_field(name="⚠️ Варны", value=f"{'🔴' if warns > 0 else '🟢'} {warns}/5", inline=True)
    embed.add_field(name="🏆 Топ", value=f"#{position} на сервере", inline=True)
    
    embed.add_field(name="🪙 Монеты", value=f"**{int(coins)}**", inline=True)
    embed.add_field(name="🎚️ Уровень", value=f"**{level}**", inline=True)
    embed.add_field(name="✨ XP", value=f"**{xp}/{next_level_xp}**", inline=True)
    
    embed.add_field(name="📈 Прогресс", value=progress_bar, inline=False)
    
    embed.add_field(name="💬 Сообщения", value=f"**{msg_count}**", inline=True)
    embed.add_field(name="🎤 В голосе", value=f"**{voice_minutes}** мин", inline=True)
    
    embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== /top ==================
@bot.tree.command(name="top", description="Топ игроков по монетам")
async def top_command(interaction: discord.Interaction):
    pool = await wait_for_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT coins.user_id, coins.balance, xp.level 
            FROM coins 
            LEFT JOIN xp ON coins.user_id = xp.user_id AND coins.guild_id = xp.guild_id
            WHERE coins.guild_id = $1
            ORDER BY coins.balance DESC 
            LIMIT 10
        ''', interaction.guild_id)
    
    if not rows:
        await interaction.response.send_message("❌ Нет данных", ephemeral=True)
        return
    
    embed = discord.Embed(title="🏆 Топ по монетам на этом сервере", color=discord.Color.gold())
    
    medals = ["🥇", "🥈", "🥉", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹"]
    
    for i, row in enumerate(rows, 1):
        user = interaction.guild.get_member(row['user_id'])
        name = user.display_name if user else f"Неизвестный"
        level = row['level'] or 1
        embed.add_field(
            name=f"{medals[i-1]} {i}. {name}",
            value=f"🪙 {int(row['balance'])} монет • 🎚️ {level} уровень",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== /marry ==================
@bot.tree.command(name="marry", description="Предложить пожениться")
@app_commands.describe(partner="Пользователь, которому предлагаешь")
async def marry_command(interaction: discord.Interaction, partner: discord.Member):
    if partner.id == interaction.user.id:
        return await interaction.response.send_message("❌ Нельзя жениться на себе", ephemeral=True)
    
    if partner.bot:
        return await interaction.response.send_message("❌ Нельзя жениться на боте", ephemeral=True)
    
    pool = await wait_for_db()
    async with pool.acquire() as conn:
        for uid in [interaction.user.id, partner.id]:
            row = await conn.fetchrow('SELECT partner_id FROM marriages WHERE user_id = $1 AND guild_id = $2', uid, interaction.guild_id)
            if row:
                return await interaction.response.send_message(f"❌ {interaction.user.mention if uid == interaction.user.id else partner.mention} уже в браке", ephemeral=True)
    
    class MarryView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="✅ Согласиться", style=discord.ButtonStyle.green)
        async def accept(self, interaction2: discord.Interaction, button: discord.ui.Button):
            if interaction2.user.id != partner.id:
                return await interaction2.response.send_message("❌ Только партнёр может согласиться", ephemeral=True)
            
            pool = await wait_for_db()
            async with pool.acquire() as conn:
                now = datetime.now()
                await conn.execute('INSERT INTO marriages (user_id, guild_id, partner_id, married_since) VALUES ($1, $2, $3, $4)',
                                  interaction.user.id, interaction.guild_id, partner.id, now)
                await conn.execute('INSERT INTO marriages (user_id, guild_id, partner_id, married_since) VALUES ($1, $2, $3, $4)',
                                  partner.id, interaction.guild_id, interaction.user.id, now)
            
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

# ================== КОМАНДА /ai (НЕЙРОСЕТЬ) ==================
@bot.tree.command(name="ai", description="Поговорить с нейросетью")
@app_commands.describe(
    prompt="Твой вопрос или сообщение",
    reset="Очистить историю диалога (да/нет)"
)
async def ai_command(interaction: discord.Interaction, prompt: str, reset: str = "нет"):
    if not AI_TOKEN:
        await interaction.response.send_message("❌ API ключ не настроен. Обратись к администратору.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    user_id = str(interaction.user.id)
    
    if reset.lower() == "да":
        user_conversations[user_id] = []
        await interaction.followup.send("🧹 История диалога очищена!")
        return
    
    if user_id not in user_conversations:
        user_conversations[user_id] = [
            {"role": "system", "content": "Ты полезный ассистент. Отвечай на русском языке кратко и по делу."}
        ]
    
    user_conversations[user_id].append({"role": "user", "content": prompt})
    
    if len(user_conversations[user_id]) > 11:
        user_conversations[user_id] = [user_conversations[user_id][0]] + user_conversations[user_id][-10:]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_TOKEN}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://discord.com",
                    "X-Title": "Discord Bot"
                },
                json={
                    "model": "google/gemma-2-9b-it:free",
                    "messages": user_conversations[user_id],
                    "max_tokens": 500
                }
            ) as resp:
                data = await resp.json()
                
                if resp.status == 200:
                    answer = data['choices'][0]['message']['content']
                else:
                    await interaction.followup.send(f"❌ Ошибка API: {data}")
                    return
        
        user_conversations[user_id].append({"role": "assistant", "content": answer})
        
        if len(answer) > 1900:
            await interaction.followup.send(answer[:1900] + "...")
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка: {str(e)}")

# ================== ТИКЕТЫ ==================
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Открыть тикет", style=discord.ButtonStyle.green)
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for ch in interaction.guild.channels:
            if ch.name == f"ticket-{interaction.user.name.lower()}":
                return await interaction.response.send_message("❌ Тикет уже есть", ephemeral=True)
        
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
        
        await interaction.response.send_message(f"✅ Тикет: {channel.mention}", ephemeral=True)
        await channel.send(embed=discord.Embed(title="📩 Тикет", description="Опиши проблему", color=discord.Color.green()), view=TicketCloseView())

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.red)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📦 Архивация...", ephemeral=True)
        
        msgs = []
        async for m in interaction.channel.history(limit=100, oldest_first=True):
            if not m.author.bot:
                msgs.append(f"[{m.created_at.strftime('%d.%m %H:%M')}] {m.author.display_name}: {m.content}")
        
        embed = discord.Embed(title=f"📦 {interaction.channel.name}", color=discord.Color.dark_gray())
        embed.add_field(name="👤 Закрыл", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
        embed.add_field(name="🎭 Роли", value=", ".join([r.name for r in interaction.user.roles if r.name != "@everyone"]) or "Нет", inline=True)
        embed.add_field(name="💬 Сообщений", value=len(msgs), inline=True)
        
        archive = interaction.guild.get_channel(ARCHIVE_CHANNEL_ID)
        if archive:
            await archive.send(embed=embed)
            if msgs:
                text = "\n".join(msgs)
                if len(text) > 1900:
                    for i in range(0, len(text), 1900):
                        await archive.send(f"```{text[i:i+1900]}```")
                else:
                    await archive.send(f"```{text}```")
        
        await interaction.channel.delete()

@bot.tree.command(name="ticket", description="Панель тикетов")
@app_commands.checks.has_any_role(ROLES["admin"])
async def ticket_panel(interaction: discord.Interaction):
    embed = discord.Embed(title="🎫 Поддержка", description="Нажми кнопку для открытия тикета", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, view=TicketView())

# ================== ЗАПУСК ==================
@bot.event
async def on_ready():
    await init_db()
    bot.loop.create_task(check_expired_warns())
    print(f"✅ {bot.user} готов! Серверов: {len(bot.guilds)}")
    print(f"🤖 Нейросеть: {'доступна' if AI_TOKEN else 'не настроена'}")
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())

bot.run(os.getenv('BOT_TOKEN'))

