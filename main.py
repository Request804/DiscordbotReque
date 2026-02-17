import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import aiosqlite
from datetime import datetime, timedelta

# ================== ТВОИ ID (всё подставлено) ==================
GUILD_ID = 1422153897362849905  # ID твоего сервера
ARCHIVE_CHANNEL_ID = 1473352413053190188  # ID канала для архивов тикетов

ROLES = {
    "admin": 1473348779888349377,   # ID роли админа
    "mod": 1473348724745961675,      # ID роли модератора
    "support": 1473349102422196314,  # ID роли саппорта
}

# ================== НАСТРОЙКИ БОТА ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"✅ Синхронизировано на сервер {GUILD_ID}")

bot = MyBot()

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
        await db.commit()

async def check_expired_warns():
    await bot.wait_until_ready()
    while not bot.is_closed():
        seven_days_ago = datetime.now() - timedelta(days=7)
        async with aiosqlite.connect('warns.db') as db:
            await db.execute('UPDATE warns SET expired = 1 WHERE date < ? AND expired = 0', (seven_days_ago,))
            await db.commit()
        await asyncio.sleep(3600)

# ================== СЧЁТЧИК СООБЩЕНИЙ ==================
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    async with aiosqlite.connect('warns.db') as db:
        await db.execute('INSERT INTO messages (user_id, count) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET count = count + 1', (message.author.id,))
        await db.commit()
    await bot.process_commands(message)

# ================== КОМАНДЫ ==================
@bot.tree.command(name="help", description="Показать все команды")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📚 Команды", color=discord.Color.blue())
    embed.add_field(name="👤 Обычные", value="`/help` `/ping` `/rules` `/admins` `/cb`", inline=False)
    embed.add_field(name="🛡️ Модерация", value="`/clear` `/warn` `/infoplayer`", inline=False)
    embed.add_field(name="🔨 Админ", value="`/ban` `/kick` `/ticket`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Проверка задержки")
async def ping_command(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Понг! Задержка: {round(bot.latency * 1000)} мс", ephemeral=True)

@bot.tree.command(name="rules", description="Правила сервера")
async def rules_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 ПРАВИЛА", color=discord.Color.red())
    embed.add_field(name="1️⃣", value="Уважение к участникам", inline=False)
    embed.add_field(name="2️⃣", value="Без спама и рекламы", inline=False)
    embed.add_field(name="3️⃣", value="18+ запрещён", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="admins", description="Список администрации")
async def admins_command(interaction: discord.Interaction):
    admin_ids = [ROLES["admin"], ROLES["mod"]]
    admins = [f"• {m.mention} — {m.top_role.name}" for m in interaction.guild.members if any(r.id in admin_ids for r in m.roles)]
    await interaction.response.send_message(embed=discord.Embed(title="👮 Администрация", description="\n".join(admins) or "Нет", color=discord.Color.gold()), ephemeral=True)

@bot.tree.command(name="cb", description="Создать красивый embed")
@app_commands.describe(color="red/blue/green/gold/purple/orange", title="Заголовок", text="Текст")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def cb_command(interaction: discord.Interaction, color: str, title: str, text: str):
    colors = {
        "red": discord.Color.red(), "blue": discord.Color.blue(),
        "green": discord.Color.green(), "gold": discord.Color.gold(),
        "purple": discord.Color.purple(), "orange": discord.Color.orange()
    }
    embed = discord.Embed(title=title, description=text, color=colors.get(color.lower(), discord.Color.random()))
    embed.set_footer(text=f"Отправил: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
    async with aiosqlite.connect('warns.db') as db:
        await db.execute('INSERT INTO warns (user_id, moderator_id, guild_id, reason, date) VALUES (?, ?, ?, ?, ?)',
                         (member.id, interaction.user.id, interaction.guild_id, reason, datetime.now()))
        await db.commit()
        seven_days_ago = datetime.now() - timedelta(days=7)
        async with db.execute('SELECT COUNT(*) FROM warns WHERE user_id = ? AND guild_id = ? AND date > ? AND expired = 0',
                              (member.id, interaction.guild_id, seven_days_ago)) as cursor:
            warn_count = (await cursor.fetchone())[0]
    embed = discord.Embed(title="⚠️ Предупреждение", description=f"{member.mention} получил варн", color=discord.Color.orange())
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    embed.add_field(name="Всего варнов", value=f"{warn_count}/5")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    if warn_count >= 5:
        await member.ban(reason="Автобан: 5 предупреждений")
        await interaction.followup.send(embed=discord.Embed(title="🔨 Автобан", description=f"{member.mention} забанен за 5 варнов", color=discord.Color.red()), ephemeral=True)

@bot.tree.command(name="infoplayer", description="Информация об игроке")
@app_commands.describe(member="Пользователь")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def infoplayer_command(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect('warns.db') as db:
        msg = await db.execute('SELECT count FROM messages WHERE user_id = ?', (member.id,))
        msg_count = (await msg.fetchone() or [0])[0]
        seven = datetime.now() - timedelta(days=7)
        active = await db.execute('SELECT reason, date, moderator_id FROM warns WHERE user_id = ? AND guild_id = ? AND date > ? AND expired = 0 ORDER BY date DESC', (member.id, interaction.guild_id, seven))
        active_warns = await active.fetchall()
        total = await db.execute('SELECT COUNT(*) FROM warns WHERE user_id = ? AND guild_id = ?', (member.id, interaction.guild_id))
        total_warns = (await total.fetchone())[0]

    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = discord.Embed(title=f"📊 {member.display_name}", color=member.color)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="🆔 ID", value=member.id, inline=True)
    embed.add_field(name="💬 Сообщений", value=msg_count, inline=True)
    embed.add_field(name="⚠️ Активных варнов", value=f"{len(active_warns)}/5", inline=True)
    embed.add_field(name="📊 Всего варнов", value=total_warns, inline=True)
    embed.add_field(name=f"🎭 Роли [{len(roles)}]", value=" ".join(roles) if roles else "Нет", inline=False)

    if active_warns:
        text = ""
        for r, d, mid in active_warns[:5]:
            mod = interaction.guild.get_member(mid)
            text += f"• {r} — {mod.display_name if mod else '?'} ({datetime.fromisoformat(d).strftime('%d.%m')})\n"
        embed.add_field(name="📋 Последние варны", value=text, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== ТИКЕТЫ ==================
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Открыть тикет", style=discord.ButtonStyle.green)
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for ch in interaction.guild.channels:
            if ch.name == f"ticket-{interaction.user.name.lower()}":
                return await interaction.response.send_message("❌ Тикет уже есть", ephemeral=True)
        cat = discord.utils.get(interaction.guild.categories, name="ТИКЕТЫ") or await interaction.guild.create_category("ТИКЕТЫ")
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ROLES["support"]): discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(ROLES["admin"]): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        ch = await interaction.guild.create_text_channel(name=f"ticket-{interaction.user.name}", category=cat, overwrites=overwrites)
        await interaction.response.send_message(f"✅ Тикет: {ch.mention}", ephemeral=True)
        await ch.send(embed=discord.Embed(title="📩 Тикет", description="Опиши проблему"), view=TicketCloseView())

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
                await archive.send("```" + "\n".join(msgs) + "```")
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
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())

bot.run(os.getenv('BOT_TOKEN'))
