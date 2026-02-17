import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import aiosqlite
from datetime import datetime, timedelta

# ================== ТВОИ РОЛИ (ЗАМЕНИ ID) ==================
ROLES = {
    "admin": 1473348779888349377,      # ID роли админа
    "mod": 1473348724745961675,        # ID роли модератора
    "support": 1473349102422196314,    # ID роли саппорта (для тикетов)
}

# ================== НАСТРОЙКИ КАНАЛОВ ==================
ARCHIVE_CHANNEL_ID = 1473352413053190188 # ID канала для архивов тикетов (ЗАМЕНИ!)

# ================== НАСТРОЙКИ БОТА ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.messages = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Синхронизировано {len(await self.tree.fetch_commands())} команд")

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

# ================== АВТОУДАЛЕНИЕ СТАРЫХ ВАРНОВ ==================
async def check_expired_warns():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            seven_days_ago = datetime.now() - timedelta(days=7)
            async with aiosqlite.connect('warns.db') as db:
                await db.execute('''
                    UPDATE warns SET expired = 1 
                    WHERE date < ? AND expired = 0
                ''', (seven_days_ago,))
                await db.commit()
        except Exception as e:
            print(f"Ошибка при обновлении варнов: {e}")
        await asyncio.sleep(3600)

# ================== СЧЁТЧИК СООБЩЕНИЙ ==================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    async with aiosqlite.connect('warns.db') as db:
        await db.execute('''
            INSERT INTO messages (user_id, count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET count = count + 1
        ''', (message.author.id,))
        await db.commit()

    await bot.process_commands(message)

# ================== КОМАНДА /help ==================
@bot.tree.command(name="help", description="Показать все команды")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📚 Список команд", color=discord.Color.blue())
    embed.add_field(name="👤 Обычные команды", value="`/help`\n`/rules`\n`/admins`\n`/cb`", inline=False)
    embed.add_field(name="🛡️ Модерация", value="`/clear`\n`/warn`\n`/infoplayer`", inline=False)
    embed.add_field(name="🔨 Администрация", value="`/ban`\n`/kick`\n`/ticket`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== КОМАНДА /cb ==================
@bot.tree.command(name="cb", description="Создать красивый embed")
@app_commands.describe(color="Цвет (red, blue, green, gold, purple, orange)", title="Заголовок", text="Текст")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def cb_command(interaction: discord.Interaction, color: str, title: str, text: str):
    colors = {
        "red": discord.Color.red(), "blue": discord.Color.blue(),
        "green": discord.Color.green(), "gold": discord.Color.gold(),
        "purple": discord.Color.purple(), "orange": discord.Color.orange()
    }
    embed = discord.Embed(title=title, description=text, color=colors.get(color.lower(), discord.Color.random()))
    embed.set_footer(text=f"Отправил: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

# ================== КОМАНДА /clear ==================
@bot.tree.command(name="clear", description="Очистить сообщения")
@app_commands.describe(amount="Количество (1-100)")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def clear_command(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ От 1 до 100", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"✅ Удалено {len(deleted)} сообщений", ephemeral=True)

# ================== КОМАНДА /ban ==================
@bot.tree.command(name="ban", description="Забанить пользователя")
@app_commands.describe(member="Пользователь", days="Дней удаления сообщений", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"])
async def ban_command(interaction: discord.Interaction, member: discord.Member, days: int = 0, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя забанить", ephemeral=True)
    await member.ban(delete_message_days=days, reason=reason)
    embed = discord.Embed(title="🔨 Бан", description=f"{member.mention} забанен", color=discord.Color.red())
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed)

# ================== КОМАНДА /kick ==================
@bot.tree.command(name="kick", description="Выгнать пользователя")
@app_commands.describe(member="Пользователь", reason="Причина")
@app_commands.checks.has_any_role(ROLES["admin"])
async def kick_command(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("❌ Нельзя кикнуть", ephemeral=True)
    await member.kick(reason=reason)
    embed = discord.Embed(title="👢 Кик", description=f"{member.mention} выгнан", color=discord.Color.orange())
    embed.add_field(name="Причина", value=reason)
    embed.add_field(name="Модератор", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed)

# ================== КОМАНДА /admins ==================
@bot.tree.command(name="admins", description="Список администрации")
async def admins_command(interaction: discord.Interaction):
    admin_role_ids = [ROLES["admin"], ROLES["mod"]]
    admins = [f"• {m.mention} — {m.top_role.name}" for m in interaction.guild.members if any(r.id in admin_role_ids for r in m.roles)]
    embed = discord.Embed(title="👮 Администрация", description="\n".join(admins) or "Нет", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)

# ================== КОМАНДА /rules ==================
@bot.tree.command(name="rules", description="Правила сервера")
async def rules_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 ПРАВИЛА СЕРВЕРА", color=discord.Color.red())
    embed.add_field(name="1️⃣ Сосите", value="• Да, именно так", inline=False)
    embed.add_field(name="2️⃣ Уважение", value="• Относитесь с уважением\n• Без оскорблений", inline=False)
    embed.add_field(name="3️⃣ Контент", value="• 18+ запрещён\n• Спам запрещён", inline=False)
    await interaction.response.send_message(embed=embed)

# ================== КОМАНДА /warn ==================
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
    await interaction.response.send_message(embed=embed)

    if warn_count >= 5:
        await member.ban(reason="Автобан: 5 предупреждений")
        await interaction.followup.send(embed=discord.Embed(title="🔨 Автобан", description=f"{member.mention} забанен за 5 варнов", color=discord.Color.red()))

# ================== КОМАНДА /infoplayer ==================
@bot.tree.command(name="infoplayer", description="Полная информация об игроке")
@app_commands.describe(member="Пользователь")
@app_commands.checks.has_any_role(ROLES["admin"], ROLES["mod"])
async def infoplayer_command(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect('warns.db') as db:
        msg_count = 0
        async with db.execute('SELECT count FROM messages WHERE user_id = ?', (member.id,)) as cursor:
            res = await cursor.fetchone()
            msg_count = res[0] if res else 0

        seven_days_ago = datetime.now() - timedelta(days=7)
        async with db.execute('SELECT reason, date, moderator_id FROM warns WHERE user_id = ? AND guild_id = ? AND date > ? AND expired = 0 ORDER BY date DESC',
                              (member.id, interaction.guild_id, seven_days_ago)) as cursor:
            active_warns = await cursor.fetchall()

        async with db.execute('SELECT COUNT(*) FROM warns WHERE user_id = ? AND guild_id = ?', (member.id, interaction.guild_id)) as cursor:
            total_warns = (await cursor.fetchone())[0]

    bans, kicks = [], []
    async for entry in interaction.guild.audit_logs(limit=200):
        if entry.target.id == member.id:
            if entry.action == discord.AuditLogAction.ban:
                bans.append(f"• {entry.reason or 'Не указана'} — {entry.user.display_name if entry.user else 'Неизвестно'} ({entry.created_at.strftime('%d.%m.%Y')})")
            elif entry.action == discord.AuditLogAction.kick:
                kicks.append(f"• {entry.reason or 'Не указана'} — {entry.user.display_name if entry.user else 'Неизвестно'} ({entry.created_at.strftime('%d.%m.%Y')})")

    roles = [r.mention for r in member.roles if r.name != "@everyone"]

    embed = discord.Embed(title=f"📊 Информация: {member.display_name}", color=member.color, timestamp=datetime.now())
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="🆔 ID", value=member.id, inline=True)
    embed.add_field(name="📅 Регистрация", value=member.created_at.strftime("%d.%m.%Y"), inline=True)
    embed.add_field(name="📥 Присоединился", value=member.joined_at.strftime("%d.%m.%Y"), inline=True)
    embed.add_field(name="💬 Сообщений", value=msg_count, inline=True)
    embed.add_field(name=f"🎭 Роли [{len(roles)}]", value=" ".join(roles) if roles else "Нет ролей", inline=False)
    embed.add_field(name="⚠️ Активных варнов", value=f"{len(active_warns)}/5", inline=True)
    embed.add_field(name="📊 Всего варнов", value=total_warns, inline=True)

    if active_warns:
        warns_text = ""
        for i, (reason, date, mod_id) in enumerate(active_warns[:5], 1):
            mod = interaction.guild.get_member(mod_id)
            mod_name = mod.display_name if mod else "Неизвестно"
            date_str = datetime.fromisoformat(date).strftime("%d.%m.%Y")
            warns_text += f"`{i}.` **{reason}** — *{mod_name}* ({date_str})\n"
        embed.add_field(name="📋 Последние варны", value=warns_text, inline=False)

    if bans:
        embed.add_field(name="🔨 Баны", value="\n".join(bans[:3]), inline=False)
    if kicks:
        embed.add_field(name="👢 Кики", value="\n".join(kicks[:3]), inline=False)

    embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== СИСТЕМА ТИКЕТОВ ==================
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Открыть тикет", style=discord.ButtonStyle.green, custom_id="ticket_button")
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

        await interaction.response.send_message(f"✅ Тикет создан: {channel.mention}", ephemeral=True)
        await channel.send(embed=discord.Embed(title="📩 Новый тикет", description=f"Тикет открыл {interaction.user.mention}\nОпиши проблему", color=discord.Color.green()), view=TicketCloseView())

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📦 Архивация тикета...", ephemeral=True)

        channel = interaction.channel
        guild = interaction.guild

        # Собираем историю сообщений
        messages = []
        async for msg in channel.history(limit=100, oldest_first=True):
            if not msg.author.bot or msg.author.id != bot.user.id:
                time_str = msg.created_at.strftime("%d.%m.%Y %H:%M")
                messages.append(f"[{time_str}] {msg.author.display_name}: {msg.content}")

        # Кто закрыл и его роль
        closer = interaction.user
        role_names = ", ".join([r.name for r in closer.roles if r.name != "@everyone"]) or "Нет ролей"

        # Создаём embed для архива
        archive_embed = discord.Embed(
            title=f"📦 Архив тикета: {channel.name}",
            color=discord.Color.dark_gray(),
            timestamp=datetime.now()
        )
        archive_embed.add_field(name="👤 Закрыл", value=f"{closer.mention} (`{closer.id}`)", inline=True)
        archive_embed.add_field(name="🎭 Роли", value=role_names, inline=True)
        archive_embed.add_field(name="📅 Создан", value=channel.created_at.strftime("%d.%m.%Y %H:%M"), inline=True)
        archive_embed.add_field(name="💬 Всего сообщений", value=len(messages), inline=True)

        # Отправляем архив в канал
        archive_channel = guild.get_channel(ARCHIVE_CHANNEL_ID)
        if archive_channel:
            await archive_channel.send(embed=archive_embed)

            if messages:
                history_text = "\n".join(messages)
                if len(history_text) > 1900:
                    for i in range(0, len(history_text), 1900):
                        await archive_channel.send(f"```{history_text[i:i+1900]}```")
                else:
                    await archive_channel.send(f"```{history_text}```")

        await channel.delete()

@bot.tree.command(name="ticket", description="Настройка тикетов")
@app_commands.checks.has_any_role(ROLES["admin"])
async def ticket_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🎫 Система поддержки", description="Нажми кнопку, чтобы открыть тикет", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, view=TicketView())

# ================== ЗАПУСК ==================
@bot.event
async def on_ready():
    await init_db()
    bot.loop.create_task(check_expired_warns())
    print(f'✅ Бот {bot.user} готов к работе!')
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())

bot.run(os.getenv('BOT_TOKEN'))