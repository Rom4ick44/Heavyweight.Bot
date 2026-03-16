import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
import traceback
import asyncio
import re
import database as db
from config import (
    TEST_ROLE_ID, YOUNG_ROLE_ID, HVWT_ROLE_ID,
    TEST_CATEGORY_ID, YOUNG_CATEGORY_ID, HVWT_CATEGORY_ID,
    PORTFOLIO_CREATION_CHANNEL_ID, PORTFOLIO_ACCESS_ROLES,
    PORTFOLIO_REQUESTS_CHANNEL_ID,
    PORTFOLIO_LOG_CHANNEL_ID
)

RANK_TO_CATEGORY = {
    'test': TEST_CATEGORY_ID,
    'Young': YOUNG_CATEGORY_ID,
    'HVWT': HVWT_CATEGORY_ID
}

RANK_TO_ROLE = {
    'test': TEST_ROLE_ID,
    'Young': YOUNG_ROLE_ID,
    'HVWT': HVWT_ROLE_ID
}

def get_user_rank(member):
    if HVWT_ROLE_ID in [r.id for r in member.roles]:
        return 'HVWT'
    if YOUNG_ROLE_ID in [r.id for r in member.roles]:
        return 'Young'
    if TEST_ROLE_ID in [r.id for r in member.roles]:
        return 'test'
    return None

def has_access(user):
    user_roles = [r.id for r in user.roles]
    return any(role in user_roles for role in PORTFOLIO_ACCESS_ROLES)

async def refresh_portfolio_embed(channel):
    portfolio = db.get_portfolio_by_channel(channel.id)
    if not portfolio:
        return
    owner_id, rank, tier, pinned_by, _, _ = portfolio
    owner = channel.guild.get_member(owner_id)
    if not owner:
        return

    warns = db.get_warns(owner_id)

    embed = discord.Embed(
        title="📁 Личный канал участника",
        description=(
            "- Присылайте в текстовый канал видео откатов с МП (желательно геймплей от 10 минут с сильными лобби).\n"
            "- Изучайте залазы, это важно для участия в мейн-составе на каптах.\n"
            "- Пожалуйста, прикрепляйте откаты с лучшей стрельбой и демонстрацией понимания игры."
        ),
        color=0x2F3136
    )
    embed.set_author(name=owner.display_name, icon_url=owner.display_avatar.url)

    rank_display = rank if rank else "нет ранга"
    embed.add_field(name="Текущий Ранг", value=rank_display, inline=True)
    embed.add_field(name="Текущий Тир", value=str(tier) if tier else "Нет тира", inline=True)
    embed.add_field(name="Кол-во варнов", value=str(warns), inline=True)
    embed.set_footer(text=f"Владелец: {owner}")

    async for message in channel.history(limit=10):
        if message.author == channel.guild.me and message.embeds:
            await message.edit(embed=embed)
            return
    await channel.send(embed=embed)

async def create_portfolio_for_user(guild, member):
    if db.get_portfolio_by_owner(member.id):
        return None

    rank = get_user_rank(member)
    if rank:
        category_id = RANK_TO_CATEGORY.get(rank)
        db_rank = rank
    else:
        category_id = TEST_CATEGORY_ID
        db_rank = ""

    if not category_id:
        return None
    category = guild.get_channel(category_id)
    if not category:
        return None

    safe_name = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ\s\-|]', '', member.display_name).strip()
    if not safe_name:
        safe_name = str(member.id)[-6:]
    channel_name = safe_name

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=False)
    }
    for role_id in PORTFOLIO_ACCESS_ROLES:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)

    warns = db.get_warns(member.id)
    embed = discord.Embed(
        title="📁 Личный канал участника",
        description=(
            "- Присылайте в текстовый канал видео откатов с МП (желательно геймплей от 10 минут с сильными лобби).\n"
            "- Изучайте залазы, это важно для участия в мейн-составе на каптах.\n"
            "- Пожалуйста, прикрепляйте откаты с лучшей стрельбой и демонстрацией понимания игры."
        ),
        color=0x2F3136
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    rank_display = db_rank if db_rank else "нет ранга"
    embed.add_field(name="Текущий Ранг", value=rank_display, inline=True)
    embed.add_field(name="Текущий Тир", value="Нет тира", inline=True)
    embed.add_field(name="Кол-во варнов", value=str(warns), inline=True)
    embed.set_footer(text=f"Владелец: {member}")

    await new_channel.send(content=f"Добро пожаловать, {member.mention}!", embed=embed, view=PortfolioView(new_channel.id))

    thread_rp = await new_channel.create_thread(name="РП мероприятия", type=discord.ChannelType.public_thread)
    thread_gang = await new_channel.create_thread(name="MCL | Capt", type=discord.ChannelType.public_thread)

    db.create_portfolio(
        channel_id=new_channel.id,
        owner_id=member.id,
        rank=db_rank,
        tier=0,
        pinned_by=None,
        thread_rp_id=thread_rp.id,
        thread_gang_id=thread_gang.id
    )

    return new_channel

class PortfolioActionSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Удалить канал", value="delete", description="Удалить этот портфель", emoji="🗑️"),
            discord.SelectOption(label="Повысить ранг", value="rank_up", description="Повысить ранг владельца", emoji="⬆️"),
            discord.SelectOption(label="Понизить ранг", value="rank_down", description="Понизить ранг владельца", emoji="⬇️"),
            discord.SelectOption(label="Выдать варн", value="warn_add", description="Выдать предупреждение владельцу", emoji="⚠️"),
            discord.SelectOption(label="Снять варн", value="warn_remove", description="Снять одно предупреждение", emoji="✅"),
        ]
        super().__init__(placeholder="Выберите действие...", min_values=1, max_values=1, options=options, custom_id="portfolio_action")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not has_access(interaction.user):
            return await interaction.followup.send("❌ У вас нет прав для управления портфелями.", ephemeral=True)

        action = self.values[0]
        channel = interaction.channel
        portfolio = db.get_portfolio_by_channel(channel.id)
        if not portfolio:
            return await interaction.followup.send("❌ Портфель не найден в БД.", ephemeral=True)

        owner_id, current_rank, current_tier, pinned_by, _, _ = portfolio
        owner = interaction.guild.get_member(owner_id)

        if action == "delete":
            await channel.delete(reason="Портфель удалён")
            db.delete_portfolio(channel.id)
            await interaction.followup.send("✅ Канал удалён.", ephemeral=True)
            await self._log_action(interaction, f"🗑️ Портфель удалён (владелец: {owner.mention if owner else owner_id})")
            return

        asyncio.create_task(self._process_action(interaction, action, channel, owner, current_rank, current_tier))

    async def _process_action(self, interaction, action, channel, owner, current_rank, current_tier):
        try:
            log_msg = None
            rank_order = ['', 'test', 'Young', 'HVWT']

            if action == "rank_up":
                if not owner:
                    await interaction.followup.send("❌ Владелец не найден.", ephemeral=True)
                    return
                if current_rank == '':
                    next_rank = 'test'
                elif current_rank == 'test':
                    next_rank = 'Young'
                elif current_rank == 'Young':
                    next_rank = 'HVWT'
                else:
                    await interaction.followup.send("❌ Это максимальный ранг.", ephemeral=True)
                    return

                new_role = interaction.guild.get_role(RANK_TO_ROLE[next_rank])
                if new_role:
                    await owner.add_roles(new_role)
                if current_rank and current_rank != '':
                    old_role = interaction.guild.get_role(RANK_TO_ROLE[current_rank])
                    if old_role:
                        await owner.remove_roles(old_role)
                new_category = interaction.guild.get_channel(RANK_TO_CATEGORY[next_rank])
                if new_category:
                    await channel.edit(category=new_category)
                db.update_portfolio_rank(channel.id, next_rank)
                await refresh_portfolio_embed(channel)
                log_msg = f"⬆️ Ранг повышен с '{current_rank if current_rank else 'нет ранга'}' до {next_rank}"
                await interaction.followup.send(f"✅ Ранг повышен до {next_rank}.", ephemeral=True)

            elif action == "rank_down":
                if not owner:
                    await interaction.followup.send("❌ Владелец не найден.", ephemeral=True)
                    return
                if current_rank == '':
                    await interaction.followup.send("❌ У пользователя нет ранга для понижения.", ephemeral=True)
                    return
                if current_rank == 'HVWT':
                    prev_rank = 'Young'
                elif current_rank == 'Young':
                    prev_rank = 'test'
                elif current_rank == 'test':
                    prev_rank = ''
                else:
                    await interaction.followup.send("❌ Некорректный ранг.", ephemeral=True)
                    return

                old_role = interaction.guild.get_role(RANK_TO_ROLE[current_rank])
                if old_role:
                    await owner.remove_roles(old_role)
                if prev_rank:
                    new_role = interaction.guild.get_role(RANK_TO_ROLE[prev_rank])
                    if new_role:
                        await owner.add_roles(new_role)
                if prev_rank:
                    new_category = interaction.guild.get_channel(RANK_TO_CATEGORY[prev_rank])
                else:
                    new_category = interaction.guild.get_channel(TEST_CATEGORY_ID)
                if new_category:
                    await channel.edit(category=new_category)
                db.update_portfolio_rank(channel.id, prev_rank)
                await refresh_portfolio_embed(channel)
                log_msg = f"⬇️ Ранг понижен с {current_rank} до '{prev_rank if prev_rank else 'нет ранга'}'"
                await interaction.followup.send(f"✅ Ранг понижен до {'нет ранга' if not prev_rank else prev_rank}.", ephemeral=True)

            elif action == "warn_add":
                if not owner:
                    await interaction.followup.send("❌ Владелец не найден.", ephemeral=True)
                    return
                db.add_warn(owner.id)
                await refresh_portfolio_embed(channel)
                warns = db.get_warns(owner.id)
                log_msg = f"⚠️ Выдан варн (теперь всего: {warns})"
                await interaction.followup.send(f"⚠️ Варн выдан пользователю {owner.mention}.", ephemeral=True)

            elif action == "warn_remove":
                if not owner:
                    await interaction.followup.send("❌ Владелец не найден.", ephemeral=True)
                    return
                current_warns = db.get_warns(owner.id)
                if current_warns <= 0:
                    await interaction.followup.send("❌ У пользователя нет варнов.", ephemeral=True)
                    return
                db.remove_warn(owner.id)
                await refresh_portfolio_embed(channel)
                warns = db.get_warns(owner.id)
                log_msg = f"✅ Снят один варн (осталось: {warns})"
                await interaction.followup.send(f"✅ Варн снят у пользователя {owner.mention}.", ephemeral=True)

            if log_msg:
                await self._log_action(interaction, log_msg, owner)

        except Exception as e:
            print(f"Ошибка в фоне PortfolioActionSelect: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Внутренняя ошибка.", ephemeral=True)

    async def _log_action(self, interaction, action_description, owner=None):
        log_channel = interaction.guild.get_channel(PORTFOLIO_LOG_CHANNEL_ID)
        if not log_channel:
            return
        embed = discord.Embed(
            title="📋 Действие с портфелем",
            description=f"**Куратор:** {interaction.user.mention}\n**Действие:** {action_description}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if owner:
            embed.add_field(name="Владелец портфеля", value=owner.mention)
        embed.add_field(name="Канал", value=interaction.channel.mention)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await log_channel.send(embed=embed)

class PortfolioTierSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Тир 1", value="1", description="Установить тир 1"),
            discord.SelectOption(label="Тир 2", value="2", description="Установить тир 2"),
            discord.SelectOption(label="Тир 3", value="3", description="Установить тир 3"),
        ]
        super().__init__(placeholder="Выберите тир...", min_values=1, max_values=1, options=options, custom_id="portfolio_tier")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not has_access(interaction.user):
            return await interaction.followup.send("❌ У вас нет прав для управления портфелями.", ephemeral=True)

        tier = int(self.values[0])
        channel = interaction.channel

        asyncio.create_task(self._set_tier(interaction, channel, tier))

    async def _set_tier(self, interaction, channel, tier):
        try:
            db.update_portfolio_tier(channel.id, tier)
            await refresh_portfolio_embed(channel)
            await interaction.followup.send(f"✅ Установлен тир {tier}.", ephemeral=True)
            log_channel = interaction.guild.get_channel(PORTFOLIO_LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    title="📋 Изменение тира",
                    description=f"**Куратор:** {interaction.user.mention}\nУстановлен тир {tier}",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Канал", value=interaction.channel.mention)
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Ошибка в PortfolioTierSelect: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Внутренняя ошибка.", ephemeral=True)

class PromotionRequestModal(Modal, title="Запрос повышения"):
    def __init__(self, channel_id):
        super().__init__()
        self.channel_id = channel_id
        self.add_item(TextInput(
            label="Причина повышения",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
            placeholder="Опишите, почему вы хотите повыситься..."
        ))

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.children[0].value
        await interaction.response.defer(ephemeral=True)

        portfolio = db.get_portfolio_by_channel(self.channel_id)
        if not portfolio:
            return await interaction.followup.send("❌ Ошибка: портфель не найден.", ephemeral=True)

        requests_channel = interaction.guild.get_channel(PORTFOLIO_REQUESTS_CHANNEL_ID)
        if not requests_channel:
            return await interaction.followup.send("❌ Канал для запросов не настроен.", ephemeral=True)

        embed = discord.Embed(
            title="📈 Запрос повышения",
            description=f"Пользователь {interaction.user.mention} ({interaction.user}) хочет повыситься.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Портфель", value=interaction.channel.mention)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"ID портфеля: {self.channel_id}")

        await requests_channel.send(embed=embed)
        await interaction.followup.send("✅ Запрос отправлен кураторам.", ephemeral=True)

class VodRequestModal(Modal, title="Запрос разбора отката"):
    def __init__(self, channel_id):
        super().__init__()
        self.channel_id = channel_id
        self.add_item(TextInput(
            label="Ссылка на видео",
            required=True,
            placeholder="https://youtu.be/..."
        ))
        self.add_item(TextInput(
            label="Дополнительная информация",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            placeholder="Что хотите улучшить? Какие моменты разобрать?"
        ))

    async def on_submit(self, interaction: discord.Interaction):
        link = self.children[0].value
        description = self.children[1].value or "—"
        await interaction.response.defer(ephemeral=True)

        portfolio = db.get_portfolio_by_channel(self.channel_id)
        if not portfolio:
            return await interaction.followup.send("❌ Ошибка: портфель не найден.", ephemeral=True)

        requests_channel = interaction.guild.get_channel(PORTFOLIO_REQUESTS_CHANNEL_ID)
        if not requests_channel:
            return await interaction.followup.send("❌ Канал для запросов не настроен.", ephemeral=True)

        embed = discord.Embed(
            title="🎥 Запрос разбора отката",
            description=f"Пользователь {interaction.user.mention} просит разобрать откат.",
            color=discord.Color.purple()
        )
        embed.add_field(name="Ссылка", value=link, inline=False)
        embed.add_field(name="Комментарий", value=description, inline=False)
        embed.add_field(name="Портфель", value=interaction.channel.mention)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"ID портфеля: {self.channel_id}")

        await requests_channel.send(embed=embed)
        await interaction.followup.send("✅ Запрос отправлен кураторам.", ephemeral=True)

class WarnRemoveRequestModal(Modal, title="Запрос на снятие варна"):
    def __init__(self, channel_id):
        super().__init__()
        self.channel_id = channel_id
        self.add_item(TextInput(
            label="Причина снятия варна",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
            placeholder="Опишите, почему хотите снять варн..."
        ))

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.children[0].value
        await interaction.response.defer(ephemeral=True)

        portfolio = db.get_portfolio_by_channel(self.channel_id)
        if not portfolio:
            return await interaction.followup.send("❌ Ошибка: портфель не найден.", ephemeral=True)

        requests_channel = interaction.guild.get_channel(PORTFOLIO_REQUESTS_CHANNEL_ID)
        if not requests_channel:
            return await interaction.followup.send("❌ Канал для запросов не настроен.", ephemeral=True)

        embed = discord.Embed(
            title="🚫 Запрос на снятие варна",
            description=f"Пользователь {interaction.user.mention} просит снять один варн.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Портфель", value=interaction.channel.mention)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"ID портфеля: {self.channel_id}")

        await requests_channel.send(embed=embed)
        await interaction.followup.send("✅ Запрос отправлен кураторам.", ephemeral=True)

class PortfolioRequestSelect(Select):
    def __init__(self, channel_id):
        options = [
            discord.SelectOption(label="📈 Запрос повышения", value="promotion"),
            discord.SelectOption(label="🎥 Разбор отката", value="vod"),
            discord.SelectOption(label="🚫 Снять варн", value="warn_remove")
        ]
        super().__init__(placeholder="Выберите запрос...", min_values=1, max_values=1,
                         options=options, custom_id=f"request_select_{channel_id}")

    async def callback(self, interaction: discord.Interaction):
        action = self.values[0]
        if action == "promotion":
            modal = PromotionRequestModal(interaction.channel.id)
            await interaction.response.send_modal(modal)
        elif action == "vod":
            modal = VodRequestModal(interaction.channel.id)
            await interaction.response.send_modal(modal)
        elif action == "warn_remove":
            modal = WarnRemoveRequestModal(interaction.channel.id)
            await interaction.response.send_modal(modal)

class PortfolioView(View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.add_item(PortfolioActionSelect())
        self.add_item(PortfolioTierSelect())
        self.add_item(PortfolioRequestSelect(channel_id))

class CreatePortfolioView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="📂 Создать портфель", style=discord.ButtonStyle.gray, custom_id="create_portfolio")
    async def create_button_callback(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)

        try:
            if db.get_portfolio_by_owner(interaction.user.id):
                return await interaction.followup.send("❌ У вас уже есть личный канал.", ephemeral=True)

            rank = get_user_rank(interaction.user)
            if rank:
                category_id = RANK_TO_CATEGORY.get(rank)
                db_rank = rank
            else:
                category_id = TEST_CATEGORY_ID
                db_rank = ""

            if not category_id:
                return await interaction.followup.send("❌ Категория для этого ранга не настроена.", ephemeral=True)

            category = interaction.guild.get_channel(category_id)
            if not category:
                return await interaction.followup.send("❌ Категория не найдена.", ephemeral=True)

            safe_name = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ\s\-|]', '', interaction.user.display_name).strip()
            if not safe_name:
                safe_name = str(interaction.user.id)[-6:]
            channel_name = safe_name

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=False)
            }
            for role_id in PORTFOLIO_ACCESS_ROLES:
                role = interaction.guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)

            warns = db.get_warns(interaction.user.id)
            embed = discord.Embed(
                title="📁 Личный канал участника",
                description=(
                    "- Присылайте в текстовый канал видео откатов с МП (желательно геймплей от 10 минут с сильными лобби).\n"
                    "- Изучайте залазы, это важно для участия в мейн-составе на каптах.\n"
                    "- Пожалуйста, прикрепляйте откаты с лучшей стрельбой и демонстрацией понимания игры."
                ),
                color=0x2F3136
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            rank_display = db_rank if db_rank else "нет ранга"
            embed.add_field(name="Текущий Ранг", value=rank_display, inline=True)
            embed.add_field(name="Текущий Тир", value="Нет тира", inline=True)
            embed.add_field(name="Кол-во варнов", value=str(warns), inline=True)
            embed.set_footer(text=f"Владелец: {interaction.user}")

            await new_channel.send(content=f"Добро пожаловать, {interaction.user.mention}!", embed=embed, view=PortfolioView(new_channel.id))

            thread_rp = await new_channel.create_thread(name="РП мероприятия", type=discord.ChannelType.public_thread)
            thread_gang = await new_channel.create_thread(name="MCL | Capt", type=discord.ChannelType.public_thread)

            db.create_portfolio(
                channel_id=new_channel.id,
                owner_id=interaction.user.id,
                rank=db_rank,
                tier=0,
                pinned_by=None,
                thread_rp_id=thread_rp.id,
                thread_gang_id=thread_gang.id
            )

            await interaction.followup.send(f"✅ Ваш личный канал создан: {new_channel.mention}", ephemeral=True)
        except Exception as e:
            print(f"Ошибка в create_portfolio: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Внутренняя ошибка.", ephemeral=True)

class Portfolio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(CreatePortfolioView(self.bot))
        self.bot.add_view(PortfolioView(0))
        print("✅ Persistent view для портфелей и кнопки создания зарегистрированы")
        self.bot.loop.create_task(self.restore_portfolios())

    async def restore_portfolios(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)
        portfolios = db.get_all_portfolios()
        restored = 0
        for channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, _ in portfolios:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                db.delete_portfolio(channel_id)
                continue
            async for message in channel.history(limit=5):
                if message.author == channel.guild.me and message.embeds:
                    await message.edit(view=PortfolioView(channel_id))
                    restored += 1
                    break
            await asyncio.sleep(0.5)
        print(f"✅ Восстановлено {restored} портфелей")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.display_name == after.display_name:
            return
        portfolio = db.get_portfolio_by_owner(after.id)
        if not portfolio:
            return
        channel_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id = portfolio
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        safe_name = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ\s\-|]', '', after.display_name).strip()
        if not safe_name:
            safe_name = str(after.id)[-6:]
        new_name = safe_name
        if channel.name != new_name:
            await channel.edit(name=new_name)
            print(f"✅ Канал {channel.id} переименован в {new_name}")
            await refresh_portfolio_embed(channel)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        portfolio = db.get_portfolio_by_owner(member.id)
        if portfolio:
            channel = member.guild.get_channel(portfolio[0])
            if channel:
                await channel.delete(reason="Участник покинул сервер")
            db.delete_portfolio(portfolio[0])

    @commands.command(name='create_portfolio_for', aliases=['cpf'])
    @commands.has_any_role(*PORTFOLIO_ACCESS_ROLES)
    async def create_portfolio_for(self, ctx, member: discord.Member):
        if db.get_portfolio_by_owner(member.id):
            await ctx.send(f"❌ У пользователя {member.mention} уже есть портфель.")
            return

        try:
            channel = await create_portfolio_for_user(ctx.guild, member)
            if channel:
                await ctx.send(f"✅ Портфель для {member.mention} создан: {channel.mention}")
            else:
                await ctx.send("❌ Не удалось создать портфель (возможно, ошибка при создании канала).")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def fix_portfolio_names(self, ctx):
        await ctx.send("🔄 Начинаю переименование портфелей...")
        portfolios = db.get_all_portfolios()
        renamed = 0
        for channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, _ in portfolios:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            owner = ctx.guild.get_member(owner_id)
            if not owner:
                continue
            safe_name = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ\s\-|]', '', owner.display_name).strip()
            if not safe_name:
                safe_name = str(owner.id)[-6:]
            new_name = safe_name
            if channel.name != new_name:
                try:
                    await channel.edit(name=new_name)
                    renamed += 1
                    await asyncio.sleep(0.5)
                    await refresh_portfolio_embed(channel)
                except Exception as e:
                    print(f"Ошибка переименования канала {channel_id}: {e}")
        await ctx.send(f"✅ Переименовано {renamed} портфелей.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_portfolio_panel(self, ctx):
        channel = self.bot.get_channel(PORTFOLIO_CREATION_CHANNEL_ID)
        if not channel:
            return await ctx.send("❌ Канал для панели не найден. Проверьте PORTFOLIO_CREATION_CHANNEL_ID.")

        embed = discord.Embed(
            title="📁 Создание личного портфеля",
            description="Нажмите кнопку ниже, чтобы создать свой личный канал.",
            color=0x000000
        )

        view = CreatePortfolioView(self.bot)
        await channel.send(embed=embed, view=view)
        await ctx.send("✅ Панель создания портфелей установлена.")

async def setup(bot):
    await bot.add_cog(Portfolio(bot))
    print("🎉 Cog Portfolio успешно загружен")