"""
Main moderation handler orchestrating classification, warnings,
delayed message deletion, rule announcements, and detailed channel logging.
"""
import os
import html
import logging
import threading
from datetime import datetime
from typing import Optional
from telegram import Update, Bot, ParseMode, Message
from telegram.ext import CallbackContext

from .config import ModerationConfig
from .storage import ModerationStorage
from .classifier import (
    classify_message,
    CATEGORY_EXCHANGE,
    CATEGORY_EXCHANGE_REPLY,
    CATEGORY_SPAM,
    CATEGORY_CHAT
)

# Dedicated logger for moderation
os.makedirs("logs", exist_ok=True)
mod_logger = logging.getLogger("moderation")
mod_logger.setLevel(logging.INFO)
if not mod_logger.handlers:
    fh = logging.FileHandler(os.path.join("logs", "moderation.log"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    mod_logger.addHandler(fh)


WELCOME_RULES_TEXT = (
    "📢 <b>Обновление правил темы «Обмен»</b>\n\n"
    "Внимание: теперь в этой теме включена автоматическая модерация чистоты доски объявлений.\n\n"
    "✅ <b>Разрешено:</b>\n"
    "• Только текстовые объявления о покупке или продаже криптовалюты (USDT, BTC, ETH и др.) с указанием условий сделки.\n"
    "• Не более 2 активных объявлений в сутки на одного участника.\n\n"
    "❌ <b>Запрещено:</b>\n"
    "• Ответы и комментарии под объявлениями (для связи пишите автору сделки в личные сообщения (ЛС) либо в основном чате!).\n"
    "• Стикеры, GIF-анимации, фотографии, видео, голосовые и видеокружочки.\n"
    "• Обычное общение, вопросы, споры и флуд.\n"
    "• Спам, реклама сторонних каналов и сервисов.\n\n"
    "⚠️ <b>Важно:</b>\n"
    "• Если необходимо изменить цену или объем — <i>отредактируйте исходное объявление</i>.\n"
    "• Все комментарии и нарушающие сообщения удаляются автоматически после предупреждения."
)


def is_service_message(message: Message) -> bool:
    """Check if the message is a Telegram system/service notification."""
    if not message:
        return True
    if (
        message.new_chat_members
        or message.left_chat_member
        or message.pinned_message
        or message.new_chat_title
        or message.new_chat_photo
        or message.delete_chat_photo
        or message.group_chat_created
        or message.supergroup_chat_created
        or message.channel_chat_created
        or getattr(message, "forum_topic_created", None)
        or getattr(message, "forum_topic_closed", None)
        or getattr(message, "forum_topic_reopened", None)
        or getattr(message, "forum_topic_edited", None)
    ):
        return True
    return False


class ModerationManager:
    def __init__(self, config: Optional[ModerationConfig] = None, storage: Optional[ModerationStorage] = None):
        self.config = config or ModerationConfig()
        self.storage = storage or ModerationStorage()

    def send_log_to_channel(self, bot: Bot, log_type: str, user_title: str, user_id: int, category: str, reason: str, text: str, action: str):
        """Send formatted moderation event log to configured Telegram channel."""
        if not self.config.log_channel_id:
            return

        def _send():
            try:
                escaped_text = html.escape(text[:350]) if text else "<i>[медиафайл / пусто]</i>"
                escaped_title = html.escape(user_title)
                escaped_reason = html.escape(reason)
                escaped_action = html.escape(action)

                log_entry = (
                    f"<b>{html.escape(log_type)}</b>\n\n"
                    f"👤 <b>Пользователь:</b> <a href=\"tg://user?id={user_id}\">{escaped_title}</a> (<code>{user_id}</code>)\n"
                    f"🏷 <b>Категория:</b> <code>{category}</code>\n"
                    f"📌 <b>Причина:</b> {escaped_reason}\n"
                    f"⚡️ <b>Действие:</b> <b>{escaped_action}</b>\n\n"
                    f"💬 <b>Текст сообщения:</b>\n<blockquote>{escaped_text}</blockquote>"
                )
                bot.send_message(
                    chat_id=self.config.log_channel_id,
                    text=log_entry,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            except Exception as e:
                mod_logger.error(f"Failed to send log to moderation channel: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def send_welcome_rules_if_needed(self, bot: Bot):
        """Sends rules welcome message once if enabled and not sent yet."""
        if not self.config.enabled or not self.config.welcome_message_enabled:
            return
        if self.storage.is_welcome_sent():
            return
        if not self.config.target_group_id:
            mod_logger.warning("Welcome message skipped: TARGET_GROUP_ID is not configured.")
            return

        try:
            msg = bot.send_message(
                chat_id=self.config.target_group_id,
                text=WELCOME_RULES_TEXT,
                parse_mode=ParseMode.HTML,
                message_thread_id=self.config.target_thread_id
            )
            self.storage.mark_welcome_sent(msg.message_id)
            mod_logger.info(f"Welcome rules message posted successfully. Message ID: {msg.message_id}")
            self.send_log_to_channel(
                bot,
                log_type="📢 [ПРАВИЛА: ПУБЛИКАЦИЯ В ТОПИК]",
                user_title="Бот",
                user_id=bot.id,
                category="RULES",
                reason="Первоначальная публикация правил темы",
                text="Опубликовано обновление правил темы «Обмен»",
                action="ОПУБЛИКОВАНО"
            )
        except Exception as e:
            mod_logger.error(f"Failed to post welcome rules message: {e}")

    def is_target_scope(self, update: Update) -> bool:
        """Verify that message belongs to monitored group and thread."""
        message = update.effective_message
        if not message or not message.chat:
            return False

        # Must be in target group if specified
        if self.config.target_group_id is not None:
            if message.chat.id != self.config.target_group_id:
                return False

        # Must be in target thread/topic if specified
        if self.config.target_thread_id is not None:
            if message.message_thread_id != self.config.target_thread_id:
                return False

        return True

    def schedule_delayed_deletion(self, bot: Bot, chat_id: int, original_msg_id: int, warning_msg_id: int, delay_secs: int):
        """Schedule deletion of both original violator message and warning reply."""
        def _delete_job():
            # 1. Delete original violating message
            try:
                bot.delete_message(chat_id=chat_id, message_id=original_msg_id)
                mod_logger.info(f"Deleted original message {original_msg_id} in chat {chat_id}")
            except Exception as e:
                mod_logger.warning(f"Could not delete original message {original_msg_id}: {e}")

            # 2. Delete warning reply
            try:
                bot.delete_message(chat_id=chat_id, message_id=warning_msg_id)
                mod_logger.info(f"Deleted warning reply {warning_msg_id} in chat {chat_id}")
            except Exception as e:
                mod_logger.warning(f"Could not delete warning reply {warning_msg_id}: {e}")

        timer = threading.Timer(delay_secs, _delete_job)
        timer.daemon = True
        timer.start()

    def handle_message(self, update: Update, context: CallbackContext):
        """Main handler for incoming messages in moderated topic."""
        if not self.config.enabled:
            return

        if not self.is_target_scope(update):
            return

        message = update.effective_message
        user = update.effective_user
        if not message or not user:
            return

        # Ignore Telegram system/service messages
        if is_service_message(message):
            return

        # 1. Ignore bot's own messages
        if user.id == context.bot.id:
            return

        # 2. Check exemptions (admins/whitelist)
        if self.config.is_user_exempt(user.id):
            return

        # 3. Classify message
        category, reason = classify_message(
            message,
            bot_user_id=context.bot.id,
            allow_replies=self.config.allow_replies_to_ads
        )

        chat_id = message.chat_id
        message_id = message.message_id
        user_id = user.id
        user_title = user.full_name or user.username or str(user.id)
        msg_text = (message.text or message.caption or "")

        # 4. Handle classification outcome
        if category in (CATEGORY_EXCHANGE, CATEGORY_EXCHANGE_REPLY):
            if category == CATEGORY_EXCHANGE:
                # Check active ad limits per user (default: max 2 ads per 24 hours)
                recent_ads = self.storage.get_user_recent_ads(user_id)
                
                if len(recent_ads) >= self.config.max_active_ads_per_user:
                    reason = (
                        f"Превышен лимит объявлений (максимум {self.config.max_active_ads_per_user} в сутки). "
                        "Пожалуйста, отредактируйте ваши существующие объявления вместо создания новых."
                    )
                    category = CATEGORY_SPAM
                    log_type = "⏳ [УДАЛЕНИЕ: ЛИМИТ 2 В СУТКИ]"
                else:
                    self.storage.register_ad(user_id, message_id, datetime.now().timestamp(), msg_text)
                    mod_logger.info(
                        f"ACCEPTED {category} | User: {user_id} | Msg: {message_id} | Reason: {reason}"
                    )
                    self.send_log_to_channel(
                        context.bot,
                        log_type="✅ [ОБЪЯВЛЕНИЕ: ОПУБЛИКОВАНО]",
                        user_title=user_title,
                        user_id=user_id,
                        category=category,
                        reason=reason,
                        text=msg_text,
                        action="ОДОБРЕНО"
                    )
                    return

        if category in (CATEGORY_SPAM, CATEGORY_CHAT):
            # Select granular log prefix based on violation nature
            if not locals().get("log_type"):
                if category == CATEGORY_SPAM:
                    log_type = "🗑 [УДАЛЕНИЕ: СПАМ / МЕДИА]"
                elif message.reply_to_message:
                    log_type = "💬 [УДАЛЕНИЕ: ЧАТ / ОТВЕТ В ТЕМЕ]"
                else:
                    log_type = "💬 [УДАЛЕНИЕ: НЕ ОБЪЯВЛЕНИЕ / ЧАТ]"

            delay = self.config.warning_delete_delay
            escaped_reason = html.escape(reason)
            warning_text = (
                f"⚠️ <b>В теме «Обмен» действуют правила модерации.</b>\n\n"
                f"<b>Причина:</b> {escaped_reason}.\n\n"
                f"<i>Для изменения условий сделки редактируйте исходное объявление.</i>\n"
                f"⏳ Сообщение и это предупреждение будут удалены через {delay} сек."
            )

            warning_msg_id = None
            try:
                reply_msg = message.reply_text(
                    warning_text,
                    parse_mode=ParseMode.HTML
                )
                warning_msg_id = reply_msg.message_id
            except Exception as e:
                mod_logger.error(f"Failed to post warning reply to msg {message_id}: {e}")

            action_desc = f"УДАЛЕНИЕ (таймаут {delay}с)"
            mod_logger.info(
                f"VIOLATION {category} | User: {user_id} | Msg: {message_id} | "
                f"Reason: {reason} | WarningMsg: {warning_msg_id} | Scheduled delete in {delay}s"
            )

            self.send_log_to_channel(
                context.bot,
                log_type=log_type,
                user_title=user_title,
                user_id=user_id,
                category=category,
                reason=reason,
                text=msg_text,
                action=action_desc
            )

            if warning_msg_id:
                self.schedule_delayed_deletion(context.bot, chat_id, message_id, warning_msg_id, delay)
            else:
                try:
                    context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception as e:
                    mod_logger.error(f"Immediate deletion error: {e}")

    def handle_edited_message(self, update: Update, context: CallbackContext):
        """Track edits to prevent duplicate ads while allowing updates."""
        if not self.config.enabled or not self.is_target_scope(update):
            return

        message = update.edited_message
        user = update.effective_user
        if not message or not user:
            return

        if is_service_message(message):
            return

        new_text = (message.text or message.caption or "")
        self.storage.update_ad_text(user.id, message.message_id, new_text)
        user_title = user.full_name or user.username or str(user.id)
        mod_logger.info(f"EDITED | User: {user.id} | Msg: {message.message_id} updated text.")

        self.send_log_to_channel(
            context.bot,
            log_type="✏️ [ОБЪЯВЛЕНИЕ: ОТРЕДАКТИРОВАНО]",
            user_title=user_title,
            user_id=user.id,
            category="EDIT",
            reason="Пользователь обновил текст объявления",
            text=new_text,
            action="ОТРЕДАКТИРОВАНО"
        )
