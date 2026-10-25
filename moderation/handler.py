"""
Main moderation handler orchestrating classification, warnings,
delayed message deletion, and rule announcements.
"""
import os
import logging
import threading
from datetime import datetime
from typing import Optional
from telegram import Update, Bot
from telegram.ext import CallbackContext

from .config import ModerationConfig
from .storage import ModerationStorage
from .classifier import (
    classify_message,
    CATEGORY_EXCHANGE,
    CATEGORY_EXCHANGE_REPLY,
    CATEGORY_SPAM,
    CATEGORY_CHAT,
    CATEGORY_UNKNOWN
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
    "📢 *Обновление правил темы «Обмен»*\n\n"
    "Внимание: теперь в этой теме включена автоматическая модерация.\n\n"
    "✅ *Разрешено:*\n"
    "• Текстовые объявления о покупке или продаже криптовалюты (USDT, BTC, ETH и др.) с указанием условий или цены.\n"
    "• Текстовые ответы участникам в ветке объявления.\n\n"
    "❌ *Запрещено:*\n"
    "• Стикеры, GIF-анимации, фотографии, видео, голосовые и видеокружочки.\n"
    "• Обычное общение, флуд и вопросы не по теме обмена.\n"
    "• Спам, ссылки на сторонние ресурсы и каналы.\n\n"
    "⚠️ *Важно:*\n"
    "• Если вам необходимо изменить цену, объём или детали сделки — *отредактируйте исходное сообщение*.\n"
    "• Нарушающие сообщения будут удаляться автоматически после предупреждения."
)


class ModerationManager:
    def __init__(self, config: Optional[ModerationConfig] = None, storage: Optional[ModerationStorage] = None):
        self.config = config or ModerationConfig()
        self.storage = storage or ModerationStorage()

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
                parse_mode="Markdown",
                message_thread_id=self.config.target_thread_id
            )
            self.storage.mark_welcome_sent(msg.message_id)
            mod_logger.info(f"Welcome rules message posted successfully. Message ID: {msg.message_id}")
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
        thread_id = message.message_thread_id

        # 4. Handle classification outcome
        if category in (CATEGORY_EXCHANGE, CATEGORY_EXCHANGE_REPLY):
            if category == CATEGORY_EXCHANGE:
                # Check active ad limits per user
                existing_ad = self.storage.get_user_ad(user_id)
                text = (message.text or message.caption or "")
                
                # If user already has an active ad and limit is 1
                if existing_ad and self.config.max_active_ads_per_user <= 1:
                    ad_age = datetime.now().timestamp() - existing_ad.get("timestamp", 0)
                    # If existing ad was within last 24 hours, ask to edit old ad
                    if ad_age < 86400:
                        reason = (
                            "У вас уже есть активное объявление в теме. "
                            "Пожалуйста, отредактируйте ваше существующее объявление вместо создания нового."
                        )
                        category = CATEGORY_SPAM

                if category == CATEGORY_EXCHANGE:
                    self.storage.register_ad(user_id, message_id, datetime.now().timestamp(), text)
                    mod_logger.info(
                        f"ACCEPTED {category} | User: {user_id} | Msg: {message_id} | Reason: {reason}"
                    )
                    return

        if category in (CATEGORY_SPAM, CATEGORY_CHAT):
            # Formulate warning message
            delay = self.config.warning_delete_delay
            warning_text = (
                f"⚠️ *В теме «Обмен» действуют правила модерации.*\n\n"
                f"*Причина:* {reason}.\n\n"
                f"_Для изменения условий сделки редактируйте исходное сообщение._\n"
                f"⏳ Сообщение и это предупреждение будут удалены через {delay} сек."
            )

            warning_msg_id = None
            try:
                reply_msg = message.reply_text(
                    warning_text,
                    parse_mode="Markdown"
                )
                warning_msg_id = reply_msg.message_id
            except Exception as e:
                mod_logger.error(f"Failed to post warning reply to msg {message_id}: {e}")

            mod_logger.info(
                f"VIOLATION {category} | User: {user_id} | Msg: {message_id} | "
                f"Reason: {reason} | WarningMsg: {warning_msg_id} | Scheduled delete in {delay}s"
            )

            if warning_msg_id:
                self.schedule_delayed_deletion(context.bot, chat_id, message_id, warning_msg_id, delay)
            else:
                # If reply failed, delete immediately
                try:
                    context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception as e:
                    mod_logger.error(f"Immediate deletion error: {e}")

        elif category == CATEGORY_UNKNOWN:
            mod_logger.warning(
                f"UNKNOWN | User: {user_id} | Msg: {message_id} | Thread: {thread_id} | "
                f"Text: {message.text or message.caption} | Reason: {reason}"
            )

    def handle_edited_message(self, update: Update, context: CallbackContext):
        """Track edits to prevent duplicate ads while allowing updates."""
        if not self.config.enabled or not self.is_target_scope(update):
            return

        message = update.edited_message
        user = update.effective_user
        if not message or not user:
            return

        new_text = (message.text or message.caption or "")
        self.storage.update_ad_text(user.id, message.message_id, new_text)
        mod_logger.info(f"EDITED | User: {user.id} | Msg: {message.message_id} updated text.")
