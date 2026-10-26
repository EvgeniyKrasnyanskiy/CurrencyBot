"""
Unit tests for Exchange topic moderation classifier and logic.
"""
import unittest
from unittest.mock import MagicMock
from moderation.classifier import (
    classify_message,
    CATEGORY_EXCHANGE,
    CATEGORY_EXCHANGE_REPLY,
    CATEGORY_SPAM,
    CATEGORY_CHAT
)

class TestModerationClassifier(unittest.TestCase):
    def _create_mock_message(self, text=None, is_sticker=False, is_photo=False, is_voice=False, reply_to=None, user_id=11111):
        msg = MagicMock()
        msg.text = text
        msg.caption = None
        msg.sticker = MagicMock() if is_sticker else None
        msg.photo = [MagicMock()] if is_photo else []
        msg.voice = MagicMock() if is_voice else None
        msg.animation = None
        msg.video_note = None
        msg.video = None
        msg.audio = None
        msg.document = None
        msg.reply_to_message = reply_to
        msg.forum_topic_created = None
        msg.message_thread_id = None
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        return msg

    def _create_mock_reply(self, user_id=99999, message_id=555, is_topic_created=False):
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = user_id
        reply.message_id = message_id
        reply.forum_topic_created = MagicMock() if is_topic_created else None
        return reply

    def test_valid_crypto_exchange_announcements(self):
        valid_samples = [
            "Продам 1000 USDT по 95.5 рублей",
            "Куплю BTC за рубли Сбер / Т-Банк",
            "Обменяю TON на наличку USD Москва",
            "Продам эфир ETH 2.5 шт",
            "Куплю USDT за нал в СПБ",
            "Sell 5000 USDT for cash RUB",
            "Куплю биткоин по хорошему курсу",
            "Продам 350usd по 82 на карту",
            "Куплю 500$ за рубли Т-Банк",
            "Продам 1000usdt по 95 на Сбер",
            "Обменяю 200 eur на наличные",
            "Куплю 0.5btc за нал",
            "Продам 500 баксов за рубли",
            "Куплю 100долларов по 80"
        ]
        for sample in valid_samples:
            msg = self._create_mock_message(text=sample)
            category, reason = classify_message(msg)
            self.assertEqual(category, CATEGORY_EXCHANGE, f"Failed for: {sample} (got {category}: {reason})")

    def test_non_crypto_casual_chat(self):
        chat_samples = [
            "Куплю кофе и булочку",
            "Продам гараж в Москве",
            "Привет всем, как дела?",
            "Кто тут админ?",
            "Спасибо за помощь!",
            "Подскажите пожалуйста где найти информацию",
            "Перевел 5000 рублей на карту"
        ]
        for sample in chat_samples:
            msg = self._create_mock_message(text=sample)
            category, reason = classify_message(msg)
            self.assertEqual(category, CATEGORY_CHAT, f"Should be CHAT: {sample} (got {category}: {reason})")

    def test_forbidden_media(self):
        # Sticker
        msg_sticker = self._create_mock_message(is_sticker=True)
        cat, _ = classify_message(msg_sticker)
        self.assertEqual(cat, CATEGORY_SPAM)

        # Photo
        msg_photo = self._create_mock_message(is_photo=True)
        cat, _ = classify_message(msg_photo)
        self.assertEqual(cat, CATEGORY_SPAM)

        # Voice
        msg_voice = self._create_mock_message(is_voice=True)
        cat, _ = classify_message(msg_voice)
        self.assertEqual(cat, CATEGORY_SPAM)

    def test_strict_mode_rejects_replies(self):
        # Strict mode (default): replies are forbidden, redirecting to DM
        replied_msg = self._create_mock_reply(user_id=99999)
        msg = self._create_mock_message(text="Написал в ЛС, проверьте", reply_to=replied_msg, user_id=11111)
        cat, reason = classify_message(msg, bot_user_id=12345, allow_replies=False)
        self.assertEqual(cat, CATEGORY_CHAT)
        self.assertIn("личные сообщения", reason)

    def test_valid_ad_with_various_reply_contexts(self):
        ad_text = "Продам 180 usdt по 82 на карту"

        # 1. Topic root creation message as reply_to_message
        topic_root_msg = self._create_mock_reply(user_id=12345, message_id=293686, is_topic_created=True)
        msg = self._create_mock_message(text=ad_text, reply_to=topic_root_msg, user_id=11111)
        msg.message_thread_id = 293686
        cat, _ = classify_message(msg, bot_user_id=12345, allow_replies=False)
        self.assertEqual(cat, CATEGORY_EXCHANGE, "Should accept ad even with topic root reply_to_message")

        # 2. Reply to bot's pinned rate or welcome message
        bot_msg = self._create_mock_reply(user_id=12345, message_id=400)
        msg_bot_reply = self._create_mock_message(text=ad_text, reply_to=bot_msg, user_id=11111)
        cat, _ = classify_message(msg_bot_reply, bot_user_id=12345, allow_replies=False)
        self.assertEqual(cat, CATEGORY_EXCHANGE, "Should accept ad replying to bot's pinned message")

        # 3. Self-reply (e.g. quote-replying previous ad)
        self_msg = self._create_mock_reply(user_id=777, message_id=300)
        msg_self = self._create_mock_message(text=ad_text, reply_to=self_msg, user_id=777)
        cat, _ = classify_message(msg_self, bot_user_id=12345, allow_replies=False)
        self.assertEqual(cat, CATEGORY_EXCHANGE, "Should accept ad replying to oneself")

        # 4. Accidental swipe/reply to another participant with complete valid ad
        other_user_msg = self._create_mock_reply(user_id=88888, message_id=200)
        msg_other = self._create_mock_message(text=ad_text, reply_to=other_user_msg, user_id=777)
        cat, _ = classify_message(msg_other, bot_user_id=12345, allow_replies=False)
        self.assertEqual(cat, CATEGORY_EXCHANGE, "Should accept complete ad even if accidental reply")

    def test_discussion_under_ad_rejected_even_with_crypto_keywords(self):
        other_user_msg = self._create_mock_reply(user_id=88888, message_id=200)

        discussion_samples = [
            "Написал в ЛС по поводу USDT",
            "Куплю твой USDT по 80",
            "Ответь в личку по поводу TON",
            "Актуально? Куплю 100 USDT"
        ]
        for sample in discussion_samples:
            msg = self._create_mock_message(text=sample, reply_to=other_user_msg, user_id=777)
            cat, reason = classify_message(msg, bot_user_id=12345, allow_replies=False)
            self.assertEqual(cat, CATEGORY_CHAT, f"Should reject discussion comment: {sample}")
            self.assertIn("личные сообщения", reason)

    def test_optional_replies_mode(self):
        # When allow_replies=True
        replied_msg = self._create_mock_reply(user_id=99999)
        msg = self._create_mock_message(text="Написал в ЛС", reply_to=replied_msg, user_id=11111)
        cat, _ = classify_message(msg, bot_user_id=12345, allow_replies=True)
        self.assertEqual(cat, CATEGORY_EXCHANGE_REPLY)


class TestCurrencyBotRateMessage(unittest.TestCase):
    def test_recreate_pinned_rate_immediately_when_deleted(self):
        from currency_bot import CurrencyBot

        bot_instance = MagicMock(spec=CurrencyBot)
        bot_instance.config = {
            'channel_id': -100123456,
            'topic_id': 111
        }
        bot_instance.bot_message_id = 999999  # Old message ID

        mock_bot = MagicMock()
        # edit_message_text fails because message was deleted in Telegram
        mock_bot.edit_message_text.side_effect = Exception("Bad Request: message to edit not found")
        
        # New message created on replacement
        new_sent_msg = MagicMock()
        new_sent_msg.message_id = 1000001
        mock_bot.send_message.return_value = new_sent_msg

        # Bind methods to our mock instance
        bot_instance._send_and_pin_rate_message = CurrencyBot._send_and_pin_rate_message.__get__(bot_instance)
        bot_instance.update_pinned_rate_message = CurrencyBot.update_pinned_rate_message.__get__(bot_instance)

        bot_instance.update_pinned_rate_message(mock_bot, "💵 USDt = 82")

        # Verify old message was attempted
        mock_bot.edit_message_text.assert_called_once()
        # Verify new message was immediately sent and pinned
        mock_bot.send_message.assert_called_once()
        mock_bot.pin_chat_message.assert_called_once_with(-100123456, 1000001)
        self.assertEqual(bot_instance.bot_message_id, 1000001)


if __name__ == '__main__':
    unittest.main()
