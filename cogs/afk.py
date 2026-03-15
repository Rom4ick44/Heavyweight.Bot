import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import time
import re
import traceback
import asyncio
from datetime import datetime
from config import AFK_LOG_CHANNEL_ID, AFK_PANEL_CHANNEL_ID
import database as db

# Функции parse_duration и format_remaining остаются без изменений
def parse_duration(duration_str: str) -> int:
    duration_str = duration_str.lower().replace(' ', '')
    pattern = re.compile(r'^(?:(\d+)(?:ч|h))?(?:(\d+)(?:м|m))?$')
    match = pattern.fullmatch(duration_str)
    if not match:
        raise ValueError("Неверный формат времени. Используйте например: 30м, 1ч, 3ч30м, 30m, 1h, 3h30m")
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    total_seconds = hours * 3600 + minutes * 60
    if total_seconds <= 0:
        raise ValueError("Время должно быть больше нуля")
    if total_seconds > 24 * 3600:
        raise ValueError("Максимальное время AFK – 24 часа. Если вам нужно больше, оформите заявку на отпуск.")
    return total_seconds

def format_remaining(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours and minutes:
        return f"{hours}ч {minutes}м"
    elif hours:
        return f"{hours}ч"
    else:
        return f"{minutes}м"

class AfkModal(Modal, title="Уход в AFK"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.add_item(TextInput(
            label="Время AFK (до 24ч)",
            placeholder="например: 30м, 1ч, 3ч30м, 30m, 1h, 3h30m",
            required=True,
            max_length=10
        ))
        self.add_item(TextInput(
            label="Причина",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=200,
            placeholder="Кратко опишите причину"
        ))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            duration = parse_duration(self.children[0].value)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        reason = self.children[1].value
        user_id = interaction.user.id
        now = time.time()

        if await db.is_afk(user_id):
            return await interaction.response.send_message("❌ Вы уже в AFK. Сначала выйдите из AFK.", ephemeral=True)

        await db.add_afk(user_id, now, duration, reason, interaction.channel_id)

        await interaction.response.send_message(
            f"✅ Вы ушли в AFK на {format_remaining(duration)}. Причина: {reason}",
            ephemeral=True
        )

        log_channel = self.bot.get_channel(AFK_LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="⏳ Уход в AFK",
                description=f"{interaction.user.mention} ушёл в AFK.",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Время", value=format_remaining(duration), inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await log_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        traceback.print_exc()
        await interaction.response.send_message("❌ Произошла внутренняя ошибка.", ephemeral=True)


class AfkPanelView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="⏰ Уйти в AFK", style=discord.ButtonStyle.primary, custom_id="afk_go")
    async def go_afk(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AfkModal(self.bot))

    @discord.ui.button(label="📋 Список AFK", style=discord.ButtonStyle.secondary, custom_id="afk_list")
    async def list_afk(self, interaction: discord.Interaction, button: Button):
        afk_list = await db.get_all_afk()
        if not afk_list:
            return await interaction.response.send_message("📭 Сейчас никто не в AFK.", ephemeral=True)

        lines = []
        now = time.time()
        for user_id, start, duration, reason in afk_list:
            remaining = start + duration - now
            if remaining <= 0:
                continue
            user = interaction.guild.get_member(user_id)
            name = user.mention if user else f"<@{user_id}>"
            time_str = format_remaining(int(remaining))
            lines.append(f"• {name} – осталось {time_str} – {reason}")

        if not lines:
            return await interaction.response.send_message("📭 Сейчас никто не в AFK.", ephemeral=True)

        await interaction.response.send_message(
            "**Список AFK:**\n" + "\n".join(lines),
            ephemeral=True
        )

    @discord.ui.button(label="🚪 Выйти из AFK", style=discord.ButtonStyle.danger, custom_id="afk_exit")
    async def exit_afk(self, interaction: discord.Interaction, button: Button):
        if not await db.is_afk(interaction.user.id):
            return await interaction.response.send_message("❌ Вы не в AFK.", ephemeral=True)

        await db.remove_afk(interaction.user.id)
        await interaction.response.send_message("✅ Вы вышли из AFK.", ephemeral=True)

        log_channel = self.bot.get_channel(AFK_LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🚪 Выход из AFK",
                description=f"{interaction.user.mention} вышел из AFK досрочно.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await log_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


class Afk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(AfkPanelView(self.bot))
        self.check_afk_expired.start()
        print("✅ Persistent view для AFK зарегистрирован")

    def cog_unload(self):
        self.check_afk_expired.cancel()

    @tasks.loop(seconds=120)  # Увеличено до 120 секунд для снижения нагрузки
    async def check_afk_expired(self):
        await self.bot.wait_until_ready()
        now = time.time()
        afk_list = await db.get_all_afk()
        for user_id, start, duration, reason in afk_list:
            if start + duration <= now:
                await db.remove_afk(user_id)
                user = self.bot.get_user(user_id)
                if user:
                    try:
                        embed = discord.Embed(
                            title="⏰ AFK истекло",
                            description="Ваше время AFK закончилось.",
                            color=discord.Color.green()
                        )
                        await user.send(embed=embed)
                    except:
                        pass
                log_channel = self.bot.get_channel(AFK_LOG_CHANNEL_ID)
                if log_channel:
                    embed = discord.Embed(
                        title="⏰ AFK истекло",
                        description=f"Пользователь <@{user_id}> вернулся из AFK (по истечении времени).",
                        color=discord.Color.blue(),
                        timestamp=datetime.now()
                    )
                    await log_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @check_afk_expired.before_loop
    async def before_check_afk(self):
        await self.bot.wait_until_ready()

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_afk_panel(self, ctx):
        channel = self.bot.get_channel(AFK_PANEL_CHANNEL_ID)
        if not channel:
            return await ctx.send("❌ Канал для панели AFK не найден. Проверьте AFK_PANEL_CHANNEL_ID в config.")

        embed = discord.Embed(
            title="⏰ AFK панель",
            description=(
                "Уход в AFK до 24 часов.\n\n"
                "**Кнопки:**\n"
                "• ⏰ Уйти в AFK — откроется модалка для ввода времени и причины\n"
                "• 📋 Список AFK — покажет текущий список (только вам)\n"
                "• 🚪 Выйти из AFK — завершить AFK досрочно"
            ),
            color=0x2F3136,
            timestamp=datetime.now()
        )
        embed.set_footer(text="AFK система")

        view = AfkPanelView(self.bot)
        await channel.send(embed=embed, view=view)
        await ctx.send("✅ Панель AFK установлена.")

async def setup(bot):
    await bot.add_cog(Afk(bot))
    print("🎉 Cog AFK успешно загружен")