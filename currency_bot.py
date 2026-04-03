import sys
print(sys.version)

import re
import json
import requests
import logging
import os
from bs4 import BeautifulSoup
import sys
import time
import psutil
import threading
from telegram.ext import Filters
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram.error import NetworkError, RetryAfter, TimedOut
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

LOCK_FILE = 'currency_bot.lock'
RESTART_FLAG_FILE = "restart.flag"
RESTART_BLOCKED_TIME = 660  # 11 минут

if not os.path.exists('logs'):
    os.makedirs('logs')
LOG_FILE = os.path.join('logs', 'currency_bot.log')

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

def load_env_config():
    admins_str = os.getenv('ADMINS', '[]')
    try:
        admins = json.loads(admins_str)
    except json.JSONDecodeError:
        print(f"Ошибка в формате ADMINS: {admins_str}")
        admins = []

    config = {
        'token': os.getenv('BOT_TOKEN'),
        'channel_id': os.getenv('CHANNEL_ID'),
        'topic_id': os.getenv('TOPIC_ID'),
        'admins': admins,
        'sleep_time': int(os.getenv('SLEEP_TIME', '600')),
        'cache_ttl': int(os.getenv('CACHE_TTL', '300'))
    }

    if not config['token']:
        raise ValueError("BOT_TOKEN не указан в .env")
    if not config['channel_id']:
        raise ValueError("CHANNEL_ID не указан в .env")

    return config

# --- Загрузка/сохранение пользователей ---
def load_users():
    users_file = 'data/users.json'
    if not os.path.exists(users_file):
        return {}
    with open(users_file, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def save_users(users):
    users_file = 'data/users.json'
    os.makedirs('data', exist_ok=True)
    with open(users_file, 'w', encoding='utf-8-sig') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

# --- Lock-файл ---
def is_our_bot(pid):
    try:
        proc = psutil.Process(pid)
        return "currency_bot.py" in ' '.join(proc.cmdline()).lower()
    except Exception:
        return False

def create_lock():
    # Проверка флага перезапуска
    if os.path.exists(RESTART_FLAG_FILE):
        age = time.time() - os.path.getmtime(RESTART_FLAG_FILE)
        if age < RESTART_BLOCKED_TIME:
            remaining = int(RESTART_BLOCKED_TIME - age)
            print(f"⏳ Бот недавно завершался. Повторный запуск разрешён через {remaining} сек.")
            sys.exit(1)

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                existing_pid = int(f.read().strip())

            if psutil.pid_exists(existing_pid) and is_our_bot(existing_pid):
                logger.error(f"Бот уже запущен (PID {existing_pid} — это currency_bot.py)")
                print("Бот уже запущен.")
                sys.exit(1)
            else:
                logger.warning(f"Найден lock-файл с неактивным или чужим PID {existing_pid}, перезаписываем")
        except Exception as e:
            logger.warning(f"Ошибка при чтении lock-файла: {e}, перезаписываем")

    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

def remove_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

    # Устанавливаем флаг завершения
    with open(RESTART_FLAG_FILE, 'w') as f:
        f.write(datetime.now().isoformat())

def parse_exchange_rate(urls, keywords):
    result_lines = []
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            domain = url.split("//")[1].split("/")[0]
            found = False

            # CoinGecko JSON
            if "application/json" in content_type:
                data = response.json()
                if "tether" in data and "rub" in data["tether"]:
                    rate = data["tether"]["rub"]
                    result_lines.insert(0, f"🏦 CoinGecko: {rate}₽")
                else:
                    result_lines.append(f"⚠️ JSON не содержит курс: {url}")
                continue

            # HTML парсинг для OKX
            html = response.text
            if "okx.com" in domain:
                okx_patterns = [
                    r'₽\s*(\d+[.,]?\d*)',
                    r'(\d+[.,]?\d*)\s*₽',
                    r'USDT.*?(\d+[.,]?\d*)\s*RUB',
                    r'RUB.*?(\d+[.,]?\d*)\s*USDT'
                ]

                found_rates = []
                for pattern in okx_patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    for match in matches:
                        try:
                            number = float(match.replace(",", "."))
                            if 70 < number < 85:
                                found_rates.append(number)
                        except ValueError:
                            continue

                if found_rates:
                    best_rate = sum(found_rates) / len(found_rates)
                    number_str = f"{best_rate:.2f}"
                    result_lines.insert(0, f"💱 OKX: {number_str}₽")
                    found = True
                continue

            # Поиск ключевых слов
            if not found:
                for keyword in keywords:
                    pattern = re.compile(
                        rf'{re.escape(keyword)}[\s:<>\-/a-zA-Z"\'=]*?(\d+[.,]?\d*)',
                        re.IGNORECASE
                    )
                    match = pattern.search(html)
                    if match:
                        rate = match.group(1)
                        result_lines.append(f"💬 {keyword}: {rate}₽")
                        found = True
                        break

            # Fallback поиск по символу ₽
            if not found and "okx.com" not in domain:
                soup = BeautifulSoup(html, 'html.parser')
                candidates = soup.find_all(string=re.compile(r'₽\s*\d+[.,]?\d*'))
                for s in candidates:
                    match = re.search(r'₽\s*(\d+[.,]?\d*)', s)
                    if match:
                        number = float(match.group(1).replace(",", "."))
                        if number > 20:
                            number_str = f"{number:.2f}"
                            result_lines.insert(0, f"💱 OKX: {number_str}₽")
                            found = True
                            break

            if not found:
                result_lines.append(f"⚠️ Курс не найден: {url}")

        except Exception as e:
            result_lines.append(f"❌ Ошибка {url}: {e}")
            logger.warning(f"Ошибка запроса {url}: {e}")

    usdt_CG = None
    usdt_OKX = None
    URL_CG = ""
    URL_OKX = ""

    for line in result_lines:
        if line.startswith("🏦 CoinGecko:"):
            match = re.search(r"([\d.]+)", line)
            usdt_CG = match.group(1) if match else None
            URL_CG = next((url for url in urls if "coingecko.com" in url), "")
        elif line.startswith("💱 OKX:"):
            match = re.search(r"([\d.]+)", line)
            usdt_OKX = match.group(1) if match else None
            URL_OKX = next((url for url in urls if "okx.com" in url), "")

    timestamp = time.strftime("%H:%M", time.localtime())

    if usdt_CG and usdt_OKX:
        URL_CG = URL_CG.replace("(", "\\(").replace(")", "\\)")
        URL_OKX = URL_OKX.replace("(", "\\(").replace(")", "\\)")
        msg = (
            # f"💵 USDT = ₽{usdt_CG} ([CG]({URL_CG})) и ₽{usdt_OKX} ([OKX]({URL_OKX})) {timestamp}"
            # f"💵 USDt = ₽{usdt_CG}[¹]({URL_CG}) и ₽{usdt_OKX}[²]({URL_OKX}) в {timestamp}"
            f"💵 USDt = ₽[{usdt_CG}]({URL_CG}) и ₽[{usdt_OKX}]({URL_OKX}) в {timestamp}"
        )
        return msg
    else:
        result_lines.append(timestamp)
        return "\n".join(result_lines)


# --- Функция парсинга курса ---
# ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ (можно использовать как есть)
class CurrencyBot:
    def __init__(self):
        try:
            self.last_rates = ""
            self.last_update_time = 0
            self.last_message_id = None
            self.bot_message_id = None

            print("Загрузка конфигурации...")
            self.env_config = load_env_config()
            self.users = load_users()
            print("Конфигурация загружена.")

            self.token = self.env_config['token']
            self.channel_id = self.env_config['channel_id']
            self.topic_id = self.env_config['topic_id']
            self.admin_ids = self.env_config['admins']
            self.sleep_time = self.env_config['sleep_time']
            self.cache_ttl = self.env_config['cache_ttl']

            self.urls = [
                "https://www.okx.com/ru-eu/convert/usdt-to-rub",
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
            ]
            self.keywords = ["Сейчас USDT = "]

            print("Создание Updater...")
            self._build_updater()

            print("Создание потока...")
            self.thread = threading.Thread(target=self.periodic_send)
            self.thread.daemon = False

            print("CurrencyBot успешно инициализирован.")
        except Exception as e:
            print(f"❌ Ошибка в конструкторе CurrencyBot: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _build_updater(self):
        self.updater = Updater(token=self.token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.setup_handlers()

    def setup_handlers(self):
        if self.dispatcher:
            self.dispatcher.add_handler(CommandHandler('start', self.cmd_start))
            self.dispatcher.add_handler(CommandHandler('get_rate', self.cmd_get_rate))
            self.dispatcher.add_handler(CommandHandler('setinterval', self.cmd_setinterval, filters=Filters.user(user_id=self.admin_ids)))
            self.dispatcher.add_handler(CommandHandler('users', self.cmd_users, filters=Filters.user(user_id=self.admin_ids)))
            self.dispatcher.add_handler(CommandHandler('help', self.cmd_help))
            self.dispatcher.add_error_handler(self._on_dispatcher_error)

    def _on_dispatcher_error(self, update, context):
        err = context.error
        logger.error("Ошибка в обработчике Telegram: %s", err, exc_info=err)

    @staticmethod
    def _is_transient_network_error(exc):
        """Прокси недоступен, обрыв, таймаут — не фатальная ошибка конфигурации."""
        if isinstance(exc, (NetworkError, TimedOut)):
            return True
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return True
        try:
            import requests
            if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
                return True
        except Exception:
            pass
        chain = []
        e = exc
        depth = 0
        while e is not None and depth < 8:
            chain.append(e)
            e = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
            depth += 1
        for e in chain:
            if isinstance(e, (ConnectionError, TimeoutError, OSError)):
                return True
            name = type(e).__name__
            if any(x in name for x in ("Connection", "Timeout", "Proxy", "Protocol", "HTTP")):
                return True
            msg = str(e).lower()
            if any(
                x in msg
                for x in (
                    "connection",
                    "timed out",
                    "timeout",
                    "proxy",
                    "refused",
                    "unreachable",
                    "network is unreachable",
                    "name or service not known",
                    "getaddrinfo failed",
                )
            ):
                return True
        return False

    def _stop_updater_safe(self):
        try:
            self.updater.stop()
        except Exception as e:
            logger.debug("stop() updater: %s", e)

    def create_keyboard(self):
        """Создает клавиатуру с кнопкой 'Обмен'"""
        keyboard = [[InlineKeyboardButton("ОБМЕН", url="https://telegra.ph/Obmen-11-06-2")]]
        return InlineKeyboardMarkup(keyboard)

    def get_cached_rate(self):
        """Получает курс из кеша или парсит заново"""
        now = time.time()
        
        # Всегда парсим новый курс, но используем кеш для защиты от частых запросов
        if now - self.last_update_time < self.cache_ttl:
            logger.info("Кеш еще действителен, но парсим новый курс для обновления.")
        
        text = parse_exchange_rate(self.urls, self.keywords)
        self.last_rates = text
        self.last_update_time = now
        return text

    def cmd_start(self, update: Update, context: CallbackContext):
        user = update.effective_user
        if user:
            logger.info(f"/start от {user.id} @{user.username}")
            user_id = str(user.id)

            if user_id not in self.users:
                self.users[user_id] = {
                    'id': user.id,
                    'username': user.username or '',
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'registration_date': datetime.now().isoformat(),
                    'last_activity': datetime.now().isoformat()
                }
                save_users(self.users)
                logger.info(f"Добавлен новый пользователь: {user_id}")
            else:
                self.users[user_id]['last_activity'] = datetime.now().isoformat()
                self.users[user_id]['username'] = user.username or ''
                self.users[user_id]['first_name'] = user.first_name or ''
                self.users[user_id]['last_name'] = user.last_name or ''
                save_users(self.users)

        update.message.reply_text(
            "Привет! Для получения курса USDT используй команду /get_rate"
        )

    def cmd_get_rate(self, update: Update, context: CallbackContext):
        user = update.effective_user
        if not user:
            return
        user_id = str(user.id)

        if user_id in self.users:
            self.users[user_id]['last_activity'] = datetime.now().isoformat()
            save_users(self.users)

        text = self.get_cached_rate()
        keyboard = self.create_keyboard()

        update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    def cmd_help(self, update: Update, context: CallbackContext):
        help_text = (
            "📌 Доступные команды:\n"
            "/start — регистрация\n"
            "/get_rate — получить текущий курс USDT\n"
            "/help — помощь\n\n"
            "🛠 Админ:\n"
            "/setinterval <сек> — задать интервал обновления\n"
            "/users — список пользователей"
        )
        update.message.reply_text(help_text)

    def cmd_setinterval(self, update: Update, context: CallbackContext):
        args = context.args
        if not args:
            update.message.reply_text("Использование: /setinterval <секунд>")
            return
        try:
            interval = int(args[0])
            if interval < 60:
                update.message.reply_text("Интервал должен быть минимум 60 секунд.")
                return
            self.sleep_time = interval
            update.message.reply_text(f"Интервал обновления установлен: {interval} сек.")
            logger.info(f"Админ изменил интервал: {interval}")
        except ValueError:
            update.message.reply_text("Введите число.")

    def cmd_users(self, update: Update, context: CallbackContext):
        if not self.users:
            update.message.reply_text("Нет зарегистрированных пользователей.")
            return
        msg = "👥 Список пользователей:\n"
        for uid, data in self.users.items():
            username = data.get('username', '')
            first_name = data.get('first_name', '')
            last_name = data.get('last_name', '')
            reg_date = data.get('registration_date', '')
            msg += f"{uid} @{username} {first_name} {last_name} ({reg_date})\n"
        update.message.reply_text(msg)

    def find_last_bot_message(self):
        """Ищет последнее сообщение от бота в топике"""
        if self.bot_message_id is not None:
            return self.bot_message_id

        try:
            bot = self.updater.bot
            chat = bot.get_chat(self.channel_id)

            if hasattr(chat, 'pinned_message') and chat.pinned_message:
                if (chat.pinned_message.from_user and
                    chat.pinned_message.from_user.id == bot.get_me().id and
                    chat.pinned_message.message_thread_id == int(self.topic_id)):
                    self.bot_message_id = chat.pinned_message.message_id
                    logger.info(f"Найдено закреплённое сообщение: {self.bot_message_id}")
                    return self.bot_message_id
            return None
        except Exception as e:
            logger.error(f"Ошибка при поиске сообщения: {e}")
            return None

    def send_or_edit_message(self, text):
        try:
            bot = self.updater.bot
            keyboard = self.create_keyboard()
            last_message_id = self.find_last_bot_message()

            if last_message_id:
                try:
                    bot.edit_message_text(
                        chat_id=self.channel_id,
                        message_id=last_message_id,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
                    logger.info("Сообщение с курсом обновлено.")
                except Exception as edit_error:
                    if "Message is not modified" in str(edit_error):
                        logger.info("Курс не изменился — редактирование не требуется.")
                    else:
                        logger.error(f"Ошибка при редактировании: {edit_error}")
                        self.bot_message_id = None
            else:
                message = bot.send_message(
                    chat_id=self.channel_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                    message_thread_id=int(self.topic_id)
                )
                self.bot_message_id = message.message_id
                try:
                    bot.pin_chat_message(
                        chat_id=self.channel_id,
                        message_id=message.message_id
                    )
                    logger.info("Сообщение отправлено и закреплено.")
                except Exception as pin_error:
                    logger.warning(f"Не удалось закрепить: {pin_error}")
        except Exception as e:
            logger.error(f"Ошибка при отправке/редактировании: {e}")

    def periodic_send(self):
        while True:
            try:
                if not self.channel_id or not self.topic_id:
                    logger.warning("Не указан channel_id или topic_id.")
                else:
                    text = self.get_cached_rate()
                    logger.info(f"Получен курс: {text}")
                    self.send_or_edit_message(text)
            except Exception as e:
                logger.error(f"Ошибка в periodic_send: {e}")
            time.sleep(self.sleep_time)

    def run(self):
        print("▶️ Запуск run()")
        logger.info("▶️ Запуск run()")

        self.thread.start()
        logger.info("🔁 Поток обновления запущен.")

        initial = float(os.getenv("RECONNECT_INITIAL_SEC", "15"))
        max_backoff = float(os.getenv("RECONNECT_MAX_SEC", "600"))
        backoff = initial

        while True:
            try:
                self.updater.start_polling()
                logger.info("📡 Бот начал polling.")
                backoff = initial
                self.updater.idle()
                logger.info("🛑 polling завершён (idle).")
                break
            except KeyboardInterrupt:
                self._stop_updater_safe()
                raise
            except RetryAfter as e:
                wait = max(1, int(getattr(e, "retry_after", 5)))
                logger.warning("Telegram RetryAfter: ждём %s сек.", wait)
                self._stop_updater_safe()
                time.sleep(wait)
                self._rebuild_updater()
            except Exception as e:
                if not self._is_transient_network_error(e):
                    self._stop_updater_safe()
                    raise
                logger.warning(
                    "Сеть/прокси недоступны (%s). Повтор через %.0f сек.",
                    e,
                    backoff,
                )
                self._stop_updater_safe()
                time.sleep(backoff)
                backoff = min(backoff * 1.5, max_backoff)
                self._rebuild_updater()

    def _rebuild_updater(self):
        logger.info("Пересоздание Updater и переподключение к Telegram…")
        self._build_updater()

if __name__ == '__main__':
    print("📦 Запуск CurrencyBot...")
    lock_created = False
    try:
        create_lock()
        lock_created = True
        bot = CurrencyBot()
        print("✅ Бот создан. Запуск...")
        bot.run()
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        import traceback
        traceback.print_exc()
        logger.error(f"Ошибка при запуске: {e}")
    finally:
        if lock_created:
            print("🧹 Очистка lock-файла")
            remove_lock()
