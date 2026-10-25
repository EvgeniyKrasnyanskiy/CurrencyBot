"""
Message classifier for Exchange topic moderation.
Classifies messages into:
- EXCHANGE: Valid crypto exchange announcement
- EXCHANGE_REPLY: Allowed text reply (if enabled in config)
- SPAM: Forbidden media, ads, spam links
- CHAT: Regular chatting, non-crypto conversations, replies, ambiguous messages
"""
import re
from typing import Tuple, Optional
from telegram import Message

CATEGORY_EXCHANGE = "EXCHANGE"
CATEGORY_EXCHANGE_REPLY = "EXCHANGE_REPLY"
CATEGORY_SPAM = "SPAM"
CATEGORY_CHAT = "CHAT"

# Regular expressions for crypto keywords
RE_CRYPTO = re.compile(
    r'\b(usdt|tether|тезер|тэзер|btc|bitcoin|биткоин|биток|eth|ethereum|эфир|ether|'
    r'ton|тон|sol|solana|солана|trx|tron|трон|bnb|xrp|usdc|крипт[а-я]*|crypto)\b',
    re.IGNORECASE
)

# Trade actions
RE_TRADE_ACTION = re.compile(
    r'\b(куплю|покупаю|покупка|продам|продаю|продажа|обменяю|меняю|обмен|отдам|'
    r'buy|buying|sell|selling|swap|exchange)\b',
    re.IGNORECASE
)

# Fiat currencies, payment methods, cash
RE_FIAT = re.compile(
    r'\b(rub|ruble|руб[а-я]*|₽|usd|доллар[а-я]*|бакс[а-я]*|\$|eur|евро|€|'
    r'нал|наличк[а-я]*|безнал|сбер|сбербанк|тинькофф|т-банк|тбанк|альфа|сбп|карт[а-я]*|мир)\b',
    re.IGNORECASE
)

# Price / amounts indicators (numbers with optional decimals or currency symbols)
RE_NUMBERS = re.compile(r'\b\d+(?:[.,]\d+)?\b')

# Greetings and casual chat markers
RE_CASUAL_CHAT = re.compile(
    r'^(привет[а-я]*|здравствуй[а-я]*|добрый (день|вечер|утро)|хай|hello|hi|ку|'
    r'спасибо|благодарю|пожалуйста|кто тут|подскажите|помогите|как дела|'
    r'ау|админ|админы|всем привет)[.!?\s]*$',
    re.IGNORECASE
)

# External invite link patterns
RE_INVITE_LINKS = re.compile(r'(?:t\.me/(?:joinchat|\+)|telegram\.me/(?:joinchat|\+))', re.IGNORECASE)


def classify_message(message: Message, bot_user_id: Optional[int] = None, allow_replies: bool = False) -> Tuple[str, str]:
    """
    Classify a Telegram message.
    Returns: (category, reason)
    """
    # 1. Check for media types forbidden in Exchange topic
    if message.sticker:
        return CATEGORY_SPAM, "Стикеры запрещены в теме «Обмен»"
    if message.animation:
        return CATEGORY_SPAM, "GIF-анимации запрещены в теме «Обмен»"
    if message.voice:
        return CATEGORY_SPAM, "Голосовые сообщения запрещены в теме «Обмен»"
    if message.video_note:
        return CATEGORY_SPAM, "Видеосообщения (кружочки) запрещены в теме «Обмен»"
    if message.video:
        return CATEGORY_SPAM, "Видео запрещено в теме «Обмен»"
    if message.audio:
        return CATEGORY_SPAM, "Аудиозаписи запрещены в теме «Обмен»"
    if message.photo:
        return CATEGORY_SPAM, "Фотографии запрещены в теме «Обмен» (только текстовые объявления)"
    if message.document:
        return CATEGORY_SPAM, "Файлы и документы запрещены в теме «Обмен»"

    # Extract text from message or caption
    text = (message.text or message.caption or "").strip()
    if not text:
        return CATEGORY_SPAM, "Пустое или неподдерживаемое сообщение"

    # Check for unauthorized invite links
    if RE_INVITE_LINKS.search(text):
        return CATEGORY_SPAM, "Ссылки-приглашения запрещены в теме «Обмен»"

    # 2. Check reply behavior
    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        if not allow_replies:
            return (
                CATEGORY_CHAT,
                "Обсуждения и ответы в теме запрещены. Для связи с автором объявления напишите ему в личные сообщения (ЛС) либо в общем чате"
            )
        else:
            # If allowed in config and replied to another participant
            if replied_user and (bot_user_id is None or replied_user.id != bot_user_id):
                return CATEGORY_EXCHANGE_REPLY, "Ответ на сообщение другого участника в теме «Обмен»"

    # 3. Check for pure casual chat greetings
    if RE_CASUAL_CHAT.match(text):
        return CATEGORY_CHAT, "Обычное общение и приветствия не являются объявлением об обмене"

    # 4. Analyze content for crypto exchange indicators
    has_crypto = bool(RE_CRYPTO.search(text))
    has_action = bool(RE_TRADE_ACTION.search(text))
    has_fiat = bool(RE_FIAT.search(text))
    has_numbers = bool(RE_NUMBERS.search(text))

    # Case A: Clear crypto exchange announcement
    # Requires: (Action + Crypto) OR (Crypto + (Fiat or Numbers/Rates))
    if has_crypto and (has_action or has_fiat or has_numbers):
        crypto_match = RE_CRYPTO.search(text).group(0).upper()
        return CATEGORY_EXCHANGE, f"Обнаружено объявление об обмене с упоминанием {crypto_match}"

    # Case B: Action without crypto (e.g. "Куплю кофе", "Продам гараж", "Куплю билет")
    if has_action and not has_crypto:
        return CATEGORY_CHAT, "Сообщение не относится к криптовалютному обмену"

    # Case C: Ambiguous or non-crypto messages are deleted as CHAT in strict mode
    return CATEGORY_CHAT, "В теме разрешены только текстовые объявления о покупке или продаже криптовалюты"
