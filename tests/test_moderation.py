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
    def _create_mock_message(self, text=None, is_sticker=False, is_photo=False, is_voice=False, reply_to=None):
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
        return msg

    def test_valid_crypto_exchange_announcements(self):
        valid_samples = [
            "Продам 1000 USDT по 95.5 рублей",
            "Куплю BTC за рубли Сбер / Т-Банк",
            "Обменяю TON на наличку USD Москва",
            "Продам эфир ETH 2.5 шт",
            "Куплю USDT за нал в СПБ",
            "Sell 5000 USDT for cash RUB",
            "Куплю биткоин по хорошему курсу"
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
        replied_msg = MagicMock()
        replied_msg.from_user.id = 99999
        msg = self._create_mock_message(text="Написал в ЛС, проверьте", reply_to=replied_msg)
        cat, reason = classify_message(msg, bot_user_id=12345, allow_replies=False)
        self.assertEqual(cat, CATEGORY_CHAT)
        self.assertIn("личные сообщения", reason)

    def test_optional_replies_mode(self):
        # When allow_replies=True
        replied_msg = MagicMock()
        replied_msg.from_user.id = 99999
        msg = self._create_mock_message(text="Написал в ЛС", reply_to=replied_msg)
        cat, _ = classify_message(msg, bot_user_id=12345, allow_replies=True)
        self.assertEqual(cat, CATEGORY_EXCHANGE_REPLY)

if __name__ == '__main__':
    unittest.main()
