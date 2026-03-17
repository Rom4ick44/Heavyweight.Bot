import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput, Select
import json
import traceback
import asyncio
from datetime import datetime, timedelta
from enum import Enum
from config import (
    REQUEST_CHANNEL_ID, ACCEPTED_CHANNEL_ID, REJECTED_CHANNEL_ID,
    APPLICATION_BUTTON_CHANNEL_ID, APPLICATION_BANNER_URL, VOICE_CHANNEL_ID,
    ROLE_OZON, ROLE_GUEST, YOUNG_ROLE_ID, RP_ROLE_ID,
    INVITER_ROLE_ID, LEADER_ROLE_ID, DEPUTY_LEADER_ROLE_ID,
    EMOJI_ACCEPT, EMOJI_REJECT, EMOJI_CALL,
    RESULTS_CHANNEL_ID
)
import database as db

# Вопросы для обычной заявки (Main)
REGULAR_QUESTIONS = [
    "Ваш ник в игре / статик / возраст ирл",
    "Лвл в игре / онлайн / часовой пояс",
    "Ваш опыт в семьях? где состояли?",
    "Откат стрельбы (Сайга, Спешик)",
    "Цель вступления"
]

# Вопросы для RP-заявки (без отката)
RP_QUESTIONS = [
    "Ваш ник в игре / статик / возраст ирл",
    "Лвл в игре / онлайн / часовой пояс",
    "Ваш опыт в семьях? Где состояли?",
    "Цель вступления"
]

class AppStatus(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

def has_any_role(user, role_ids):
    user_roles = {r.id for r in user.roles}
    return any(rid in user_roles for rid in role_ids)

async def safe_delete(message):
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass

async def send_to_channel(channel, embed=None, embeds=None):
    if channel:
        await channel.send(embed=embed, embeds=embeds, allowed_mentions=discord.AllowedMentions.none())

def create_past_apps_text(guild, user_id):
    past_apps = db.get_user_applications(user_id)
    lines = []
    for app_id, status, date, msg_id in past_apps[:5]:
        if msg_id:
            jump_url = f"https://discord.com/channels/{guild.id}/{REQUEST_CHANNEL_ID}/{msg_id}"
            if status == AppStatus.ACCEPTED.value:
                emoji = f"<:accept:{EMOJI_ACCEPT}>" if EMOJI_ACCEPT else "✅"
            elif status == AppStatus.REJECTED.value:
                emoji = f"<:reject:{EMOJI_REJECT}>" if EMOJI_REJECT else "❌"
            else:
                emoji = "⏳"
            line = f"• [#{app_id}]({jump_url}) – {date[:10]} – {status.capitalize()} {emoji}"
        else:
            line = f"• #{app_id} – {date[:10]} – {status.capitalize()}"
        lines.append(line)
    text = "\n".join(lines)
    if not text:
        return "Нет"
    if len(text) > 1024:
        text = text[:1021] + "..."
    return text

def is_account_recent(created_at):
    return datetime.now().astimezone() - created_at < timedelta(days=30)


# Базовый класс модалки
class BaseApplicationModal(Modal):
    def __init__(self, bot, questions, app_type, title):
        super().__init__(title=title)
        self.bot = bot
        self.app_type = app_type  # 'regular' или 'rp'
        for q in questions:
            self.add_item(TextInput(
                label=q[:45],
                style=discord.TextStyle.paragraph if len(q) > 50 else discord.TextStyle.short,
                required=True,
                max_length=500,
                placeholder="Введите ответ..."
            ))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            if not db.are_applications_open():
                return await interaction.followup.send("❌ Приём заявок закрыт.", ephemeral=True)

            # Проверка на кулдаун после отклонения (7 дней)
            last_rejected = db.get_last_rejected_time(interaction.user.id)
            if last_rejected:
                days_passed = (datetime.now() - last_rejected).days
                if days_passed < 7:
                    remaining = 7 - days_passed
                    return await interaction.followup.send(
                        f"⏳ Ваша предыдущая заявка была отклонена. Вы сможете подать новую через **{remaining}** дн. (недельный кулдаун).",
                        ephemeral=True
                    )

            answers = [item.value for item in self.children]
            answers_json = json.dumps(answers, ensure_ascii=False)

            guild = interaction.guild
            user = interaction.user
            member = guild.get_member(user.id)

            embed1 = discord.Embed(title="📋 НОВАЯ ЗАЯВКА В СЕМЬЮ", color=discord.Color.light_gray())
            embed1.set_thumbnail(url=member.display_avatar.url)
            recent_warning = " ⚠️ (менее месяца)" if is_account_recent(user.created_at) else ""
            embed1.add_field(
                name="**КАНДИДАТ**",
                value=(
                    f"• **Пользователь:** {user.mention}\n"
                    f"• **ID профиля:** {user.id}{recent_warning}\n"
                    f"• **Discord tag:** {str(user)}\n"
                    f"• **Дата регистрации:** {discord.utils.format_dt(user.created_at, style='D')}\n"
                    f"• **Присоединился:** {discord.utils.format_dt(member.joined_at, style='D')}"
                ),
                inline=False
            )
            past_apps_text = create_past_apps_text(guild, user.id)
            embed1.add_field(name="**ПРОШЛЫЕ ЗАЯВКИ**", value=past_apps_text, inline=False)
            embed1.add_field(name="**СТАТУС ЗАЯВКИ**", value="⏳ Ожидает рассмотрения", inline=False)
            embed1.add_field(name="**РЕЗУЛЬТАТ РАССМОТРЕНИЯ**", value="—", inline=False)

            embed2 = discord.Embed(title="**ОТВЕТЫ НА ВОПРОСЫ**", color=0x2F3136)
            questions_used = REGULAR_QUESTIONS if self.app_type == 'regular' else RP_QUESTIONS
            for i, (q, ans) in enumerate(zip(questions_used, answers)):
                embed2.add_field(name=f"{i+1}. {q}", value=f"```{ans}```", inline=False)

            app_channel = self.bot.get_channel(REQUEST_CHANNEL_ID)
            if not app_channel:
                return await interaction.followup.send("❌ Канал заявок не найден.", ephemeral=True)

            msg = await app_channel.send(embeds=[embed1, embed2])

            ping_msg = None
            inviter_role = guild.get_role(INVITER_ROLE_ID)
            if inviter_role:
                ping_msg = await app_channel.send(
                    f"||{inviter_role.mention}||",
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )

            app_id = db.add_application(user.id, answers_json, msg.id, ping_msg.id if ping_msg else None, self.app_type)
            embed1.set_footer(text=f"ID заявки: {app_id} | Тип: {'RP' if self.app_type == 'rp' else 'Main'}")

            await msg.edit(embeds=[embed1, embed2], view=ApplicationButtons(self.bot))
            await interaction.followup.send("✅ Заявка отправлена!", ephemeral=True)

        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        traceback.print_exc()
        try:
            await interaction.followup.send("❌ Ошибка при отправке.", ephemeral=True)
        except:
            pass


# Селект для выбора типа заявки
class ApplicationTypeSelect(Select):
    def __init__(self, bot):
        self.bot = bot
        options = [
            discord.SelectOption(label="Main заявка", value="regular", description="Основная заявка в семью", emoji="📋"),
            discord.SelectOption(label="RP-заявка", value="rp", description="RP заявка без вопроса об откате", emoji="🎭")
        ]
        super().__init__(placeholder="Выберите тип заявки...", min_values=1, max_values=1, options=options, custom_id="application_type_select")

    async def callback(self, interaction: discord.Interaction):
        if not db.are_applications_open():
            return await interaction.response.send_message("❌ Приём заявок закрыт.", ephemeral=True)
        
        app_type = self.values[0]
        if app_type == 'regular':
            modal = BaseApplicationModal(self.bot, REGULAR_QUESTIONS, 'regular', "Заявка в семью (Main)")
        else:
            modal = BaseApplicationModal(self.bot, RP_QUESTIONS, 'rp', "RP-заявка")
        await interaction.response.send_modal(modal)


# View для панели выбора типа заявки (содержит селект)
class ApplicationTypeView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.add_item(ApplicationTypeSelect(bot))


# Кнопки для обработки уже созданной заявки (вызов на обзвон, принять, отклонить)
class ApplicationButtons(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    def get_application_data(self, interaction: discord.Interaction):
        message_id = interaction.message.id
        app_data = db.get_application_by_message(message_id)
        return app_data, interaction.message

    def can_interact(self, interaction: discord.Interaction, app_data):
        app_id, owner_id, _, _, _, _, claimed_by, _, _, _ = app_data
        leader_ids = [LEADER_ROLE_ID, DEPUTY_LEADER_ROLE_ID]
        if has_any_role(interaction.user, leader_ids):
            return True
        if claimed_by is None or claimed_by == interaction.user.id:
            return True
        return False

    async def update_reviewer_and_status(self, message, reviewer_id, new_status):
        if not message.embeds:
            return
        embed1 = message.embeds[0]
        embed2 = message.embeds[1]
        new_embed = discord.Embed.from_dict(embed1.to_dict())
        status_found = False
        for i, field in enumerate(new_embed.fields):
            if field.name == "**СТАТУС ЗАЯВКИ**":
                new_embed.set_field_at(i, name="**СТАТУС ЗАЯВКИ**", value=new_status, inline=False)
                status_found = True
        if not status_found:
            new_embed.add_field(name="**СТАТУС ЗАЯВКИ**", value=new_status, inline=False)

        reviewer = message.guild.get_member(reviewer_id)
        reviewer_text = f"**Рассматривает:** {reviewer.mention}" if reviewer else "—"
        for i, field in enumerate(new_embed.fields):
            if field.name == "**Рассматривает**":
                new_embed.set_field_at(i, name="**Рассматривает**", value=reviewer_text, inline=False)
                break
        else:
            new_embed.add_field(name="**Рассматривает**", value=reviewer_text, inline=False)

        try:
            await message.edit(embeds=[new_embed, embed2])
        except discord.NotFound:
            pass
        except Exception as e:
            print(f"Ошибка при редактировании сообщения заявки: {e}")

    async def _cleanup(self, message):
        app_data = db.get_application_by_message(message.id)
        if not app_data:
            return
        _, _, _, _, _, _, _, ping_id, _, _ = app_data
        if message.id:
            await safe_delete(message)
        if ping_id:
            try:
                ping = await message.channel.fetch_message(ping_id)
                await safe_delete(ping)
            except:
                pass

    @discord.ui.button(label="Вызвать на обзвон", style=discord.ButtonStyle.gray, emoji="📞", custom_id="call_application")
    async def call_callback(self, interaction: discord.Interaction, button: Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            app_data, message = self.get_application_data(interaction)
            if not app_data:
                return await interaction.followup.send("❌ Заявка не найдена в базе данных.", ephemeral=True)
            if not self.can_interact(interaction, app_data):
                return await interaction.followup.send("❌ Заявка уже обрабатывается.", ephemeral=True)

            app_id, user_id, _, _, _, _, claimed_by, _, _, _ = app_data
            member = interaction.guild.get_member(user_id)
            if not member:
                return await interaction.followup.send("❌ Пользователь не найден.", ephemeral=True)

            role_ozon = interaction.guild.get_role(ROLE_OZON)
            if not role_ozon:
                return await interaction.followup.send("❌ Роль обзвона не найдена.", ephemeral=True)

            if claimed_by is None:
                db.set_application_claimed(app_id, interaction.user.id)

            await member.add_roles(role_ozon, reason="Вызов на обзвон")
            voice_channel_id = VOICE_CHANNEL_ID[0] if isinstance(VOICE_CHANNEL_ID, tuple) else VOICE_CHANNEL_ID
            voice_channel = interaction.guild.get_channel(voice_channel_id)
            voice_link = f"https://discord.com/channels/{interaction.guild.id}/{voice_channel.id}" if voice_channel else "голосовой канал"
            try:
                embed = discord.Embed(
                    title="📞 Вызов на обзвон",
                    description=f"Вас вызвали на обзвон! Зайдите в {voice_link}.",
                    color=discord.Color.light_gray()
                )
                embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
                await member.send(embed=embed)
            except:
                pass
            await self.update_reviewer_and_status(message, interaction.user.id, "📞 Приглашён на обзвон")
            await interaction.followup.send(f"✅ Роль {role_ozon.name} выдана.", ephemeral=True)

        except Exception as e:
            traceback.print_exc()
            try:
                await interaction.followup.send(f"❌ Внутренняя ошибка: {e}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, emoji="✅", custom_id="accept_application")
    async def accept_callback(self, interaction: discord.Interaction, button: Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            app_data, message = self.get_application_data(interaction)
            if not app_data:
                return await interaction.followup.send("❌ Заявка не найдена в базе данных.", ephemeral=True)
            if not self.can_interact(interaction, app_data):
                return await interaction.followup.send("❌ Заявка уже обрабатывается.", ephemeral=True)

            app_id, user_id, answers_json, _, _, _, _, ping_id, _, app_type = app_data
            member = interaction.guild.get_member(user_id)
            if not member:
                return await interaction.followup.send("❌ Пользователь не найден.", ephemeral=True)

            role_ozon = interaction.guild.get_role(ROLE_OZON)
            role_guest = interaction.guild.get_role(ROLE_GUEST)
            
            if app_type == 'rp':
                main_role = interaction.guild.get_role(RP_ROLE_ID)
                role_name = "RP"
            else:
                main_role = interaction.guild.get_role(YOUNG_ROLE_ID)
                role_name = "Young (Main)"

            if role_ozon and role_ozon in member.roles:
                await member.remove_roles(role_ozon)
            if role_guest and role_guest in member.roles:
                await member.remove_roles(role_guest)

            if main_role:
                try:
                    await member.add_roles(main_role, reason=f"Принята {role_name} заявка")
                except discord.Forbidden:
                    print(f"❌ Нет прав для выдачи роли {main_role.name}")
                    await interaction.followup.send(f"⚠️ Не удалось выдать роль {role_name} (недостаточно прав). Обратитесь к администратору.", ephemeral=True)
                except Exception as e:
                    print(f"❌ Ошибка при выдаче роли: {e}")
                    await interaction.followup.send(f"⚠️ Ошибка при выдаче роли: {e}", ephemeral=True)
            else:
                print(f"❌ Роль {role_name} не найдена (ID: {RP_ROLE_ID if app_type=='rp' else YOUNG_ROLE_ID})")
                await interaction.followup.send(f"⚠️ Роль {role_name} не найдена. Проверьте конфигурацию.", ephemeral=True)

            db.update_application_status(app_id, AppStatus.ACCEPTED.value, interaction.user.id)

            if app_type == 'regular' and not db.get_portfolio_by_owner(member.id):
                try:
                    from cogs.portfolio import create_portfolio_for_user
                    await create_portfolio_for_user(interaction.guild, member)
                except Exception as e:
                    print(f"Ошибка при создании портфеля: {e}")

            async def background():
                try:
                    embed = discord.Embed(
                        title="✅ Заявка принята",
                        description="Поздравляем! Ваша заявка принята. Добро пожаловать в семью!",
                        color=discord.Color.green()
                    )
                    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
                    await member.send(embed=embed)
                except:
                    pass

                accepted_channel = self.bot.get_channel(ACCEPTED_CHANNEL_ID)
                if accepted_channel:
                    e1 = discord.Embed.from_dict(message.embeds[0].to_dict())
                    e2 = discord.Embed.from_dict(message.embeds[1].to_dict())
                    e1._fields = [f for f in e1._fields if f['name'] != "**РЕЗУЛЬТАТ РАССМОТРЕНИЯ**"]
                    now = datetime.now().strftime("%d.%m.%Y в %H:%M")
                    result_value = f"**Рассмотрено:** {interaction.user.mention}\n**Дата:** {now}\n**Статус:** ✅ Принята\n**Тип:** {'RP' if app_type == 'rp' else 'Main'}"
                    e1.add_field(name="**РЕЗУЛЬТАТ РАССМОТРЕНИЯ**", value=result_value, inline=False)
                    await send_to_channel(accepted_channel, embeds=[e1, e2])

                await self._cleanup(message)

            asyncio.create_task(background())
            await interaction.followup.send(f"✅ Заявка принята как {role_name}.", ephemeral=True)

        except Exception as e:
            traceback.print_exc()
            try:
                await interaction.followup.send(f"❌ Внутренняя ошибка: {e}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, emoji="❌", custom_id="reject_application")
    async def reject_callback(self, interaction: discord.Interaction, button: Button):
        try:
            app_data, message = self.get_application_data(interaction)
            if not app_data:
                return await interaction.response.send_message("❌ Заявка не найдена в базе данных.", ephemeral=True)
            if not self.can_interact(interaction, app_data):
                return await interaction.response.send_message("❌ Заявка уже обрабатывается.", ephemeral=True)
            modal = RejectModal(message.id, self.bot)
            await interaction.response.send_modal(modal)

        except Exception as e:
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Внутренняя ошибка: {e}", ephemeral=True)


class RejectModal(Modal, title="Отклонение заявки"):
    def __init__(self, message_id, bot):
        super().__init__()
        self.message_id = message_id
        self.bot = bot
        self.add_item(TextInput(
            label="Причина отказа",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
            placeholder="Укажите причину..."
        ))

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.children[0].value
        await interaction.response.send_message("✅ Заявка отклоняется...", ephemeral=True)

        async def background():
            try:
                app_data = db.get_application_by_message(self.message_id)
                if not app_data:
                    print("❌ Заявка не найдена в БД")
                    return

                app_id, user_id, answers_json, status, reviewer_id, message_id, claimed_by, ping_id, reviewed_at, app_type = app_data
                member = interaction.guild.get_member(user_id)

                if member:
                    role_ozon = interaction.guild.get_role(ROLE_OZON)
                    if role_ozon and role_ozon in member.roles:
                        await member.remove_roles(role_ozon)

                db.update_application_status(app_id, AppStatus.REJECTED.value, interaction.user.id)

                if member:
                    try:
                        embed_dm = discord.Embed(
                            title="❌ Заявка отклонена",
                            description=f"Ваша заявка отклонена.\n**Причина:** {reason}",
                            color=discord.Color.red()
                        )
                        embed_dm.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
                        await member.send(embed=embed_dm)
                    except:
                        pass

                rejected_channel = self.bot.get_channel(REJECTED_CHANNEL_ID)
                if rejected_channel:
                    try:
                        msg = await interaction.channel.fetch_message(self.message_id)
                        e1 = discord.Embed.from_dict(msg.embeds[0].to_dict())
                        e2 = discord.Embed.from_dict(msg.embeds[1].to_dict())
                        e1._fields = [f for f in e1._fields if f['name'] != "**РЕЗУЛЬТАТ РАССМОТРЕНИЯ**"]
                        now = datetime.now().strftime("%d.%m.%Y в %H:%M")
                        result_value = f"**Рассмотрено:** {interaction.user.mention}\n**Дата:** {now}\n**Статус:** ❌ Отклонена\n**Причина:** {reason}\n**Тип:** {'RP' if app_type == 'rp' else 'Main'}"
                        e1.add_field(name="**РЕЗУЛЬТАТ РАССМОТРЕНИЯ**", value=result_value, inline=False)
                        await send_to_channel(rejected_channel, embeds=[e1, e2])
                    except Exception as e:
                        print(f"Ошибка при отправке в канал отклонённых: {e}")

                results_channel = self.bot.get_channel(RESULTS_CHANNEL_ID)
                if results_channel:
                    review_time = datetime.now()
                    date_str = review_time.strftime("%d.%m.%Y")

                    embed_result = discord.Embed(
                        title="Заявка отклонена!",
                        description=f"{member.mention if member else f'<@{user_id}>'}\nВаша заявка отклонена по причине: {reason}",
                        color=discord.Color.red()
                    )
                    embed_result.add_field(name="Дата отклонения", value=date_str)
                    embed_result.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
                    embed_result.set_footer(text=f"ID заявки: {app_id} | Тип: {'RP' if app_type == 'rp' else 'Main'}")

                    await results_channel.send(embed=embed_result)

                try:
                    msg = await interaction.channel.fetch_message(self.message_id)
                    await safe_delete(msg)
                except:
                    pass
                if ping_id:
                    try:
                        ping = await interaction.channel.fetch_message(ping_id)
                        await safe_delete(ping)
                    except:
                        pass

            except Exception as e:
                print(f"Ошибка в фоне RejectModal: {e}")
                traceback.print_exc()

        asyncio.create_task(background())

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        traceback.print_exc()
        try:
            await interaction.response.send_message("❌ Внутренняя ошибка.", ephemeral=True)
        except:
            pass


class Application(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        db.init_db()
        # Регистрируем persistent views
        self.bot.add_view(ApplicationButtons(self.bot))      # для кнопок внутри заявки
        self.bot.add_view(ApplicationTypeView(self.bot))     # для панели с селектом выбора типа
        print("✅ Persistent view для заявок зарегистрированы")
        self.bot.loop.create_task(self.restore_application_buttons())

    async def restore_application_buttons(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)
        channel = self.bot.get_channel(REQUEST_CHANNEL_ID)
        if not channel:
            return
        count = 0
        async for message in channel.history(limit=200):
            if message.author == self.bot.user and len(message.embeds) == 2:
                if db.get_application_by_message(message.id):
                    await message.edit(view=ApplicationButtons(self.bot))
                    count += 1
        print(f"✅ Восстановлено {count} кнопок для заявок")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def fix_app_buttons(self, ctx):
        channel = self.bot.get_channel(REQUEST_CHANNEL_ID)
        if not channel:
            return await ctx.send("❌ Канал заявок не найден.")
        count = 0
        async for message in channel.history(limit=500):
            if message.author == self.bot.user and len(message.embeds) == 2:
                if db.get_application_by_message(message.id):
                    await message.edit(view=ApplicationButtons(self.bot))
                    count += 1
        await ctx.send(f"✅ Восстановлено {count} кнопок.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_app(self, ctx):
        channel = self.bot.get_channel(APPLICATION_BUTTON_CHANNEL_ID)
        if not channel:
            return await ctx.send("❌ Канал для кнопки не найден.")

        # Очищаем старые сообщения бота в канале
        async for message in channel.history(limit=50):
            if message.author == self.bot.user:
                try:
                    await message.delete()
                except:
                    pass
            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title="Путь в семью начинается здесь!",
            description=(
                f"Уведомление о приглашении на обзвон или отказе будет опубликовано в канале — <#{RESULTS_CHANNEL_ID}>.\n\n"
                f"Обычно заявки обрабатываются в течение 2–7 дней — всё зависит от загрузки рекрутеров."
            ),
            color=0x000000
        )
        if APPLICATION_BANNER_URL:
            embed.set_image(url=APPLICATION_BANNER_URL)

        # Используем ApplicationTypeView – содержит селект
        await channel.send(embed=embed, view=ApplicationTypeView(self.bot))
        await ctx.send("✅ Панель заявок с селектом выбора типа установлена.")

    @commands.command(name='remove_cooldown', aliases=['unban_app', 'reset_cooldown'])
    @commands.has_permissions(administrator=True)
    async def remove_cooldown(self, ctx, member: discord.Member):
        """Снять недельный кулдаун с пользователя (удалить все его отклонённые заявки)."""
        deleted = db.clear_rejected_applications(member.id)
        if deleted:
            await ctx.send(f"✅ У пользователя {member.mention} удалено {deleted} отклонённых заявок. Теперь он может подавать заявки.")
        else:
            await ctx.send(f"❌ У пользователя {member.mention} нет отклонённых заявок.")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        applications = db.get_user_applications(member.id)
        for app_id, status, date, msg_id in applications:
            if status == AppStatus.PENDING.value:
                db.update_application_status(app_id, AppStatus.REJECTED.value, self.bot.user.id)
                print(f"✅ Заявка {app_id} отклонена (пользователь покинул сервер)")

async def setup(bot):
    await bot.add_cog(Application(bot))
    print("🎉 Cog Application успешно загружен")