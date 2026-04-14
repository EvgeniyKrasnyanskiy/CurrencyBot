import os
import re
import json
import time
import logging
import threading
import psutil
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, Filters
from telegram.error import NetworkError, RetryAfter, TimedOut

load_dotenv()

# --- CONFIG & PROXY ---
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 10808
REQUEST_KWARGS = {'proxy_url': f'http://{PROXY_HOST}:{PROXY_PORT}/', 'connect_timeout': 30, 'read_timeout': 30}
PROXY_DICT = {"http": f"http://{PROXY_HOST}:{PROXY_PORT}", "https": f"http://{PROXY_HOST}:{PROXY_PORT}"}

LOCK_FILE = 'currency_bot.lock'

# Logging
if not os.path.exists('logs'): os.makedirs('logs')
logging.basicConfig(filename=os.path.join('logs', 'currency_bot.log'), level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
logger = logging.getLogger(__name__)

# --- UTILS ---
def load_env_config():
    admins = json.loads(os.getenv('ADMINS', '[]'))
    config = {
        'token': os.getenv('BOT_TOKEN'),
        'channel_id': os.getenv('CHANNEL_ID'),
        'topic_id': os.getenv('TOPIC_ID'),
        'admins': admins,
        'sleep_time': int(os.getenv('SLEEP_TIME', '600')),
        'cache_ttl': int(os.getenv('CACHE_TTL', '600'))
    }
    if not config['token'] or not config['channel_id']:
        raise ValueError("BOT_TOKEN или CHANNEL_ID не настроены в .env")
    return config

def load_users():
    if not os.path.exists('data/users.json'): return {}
    with open('data/users.json', 'r', encoding='utf-8-sig') as f: return json.load(f)

def save_users(users):
    os.makedirs('data', exist_ok=True)
    with open('data/users.json', 'w', encoding='utf-8-sig') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

# --- КОРНЕВАЯ ЛОГИКА КУРСОВ ---
def get_all_rates():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    url_link_cg = "https://www.coingecko.com/en/coins/tether/rub"
    url_link_rapira = "https://rapira.net/exchange/USDT_RUB"
    
    timestamp = datetime.now().strftime("%H:%M")
    usdt_CG = "???"
    usdt_Rapira = "???"

    to_time = int(time.time() * 1000)
    from_time = to_time - (24 * 60 * 60 * 1000)

    # 1. Rapira
    try:
        url_api_rapira = f"https://api.rapira.net/market/history?symbol=USDT/RUB&from={from_time}&to={to_time}&resolution=15"
        r = requests.get(url_api_rapira, headers=headers, timeout=10, proxies=PROXY_DICT)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            usdt_Rapira = f"{float(data[-1][4]):.2f}"
    except Exception as e:
        logger.error(f"Rapira Error: {e}")

    # 2. CoinGecko
    try:
        url_api_cg = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
        r = requests.get(url_api_cg, headers=headers, timeout=10, proxies=PROXY_DICT)
        if r.status_code == 200:
            usdt_CG = f"{float(r.json()['tether']['rub']):.2f}"
    except Exception as e:
        logger.error(f"CG Error: {e}")

    return f"💵 USDt = ₽[{usdt_Rapira}]({url_link_rapira}) и ₽[{usdt_CG}]({url_link_cg}) в {timestamp}"

# --- BOT CLASS ---
class CurrencyBot:
    def __init__(self):
        self.config = load_env_config()
        self.users = load_users()
        self.last_rates = ""
        self.last_update_time = 0
        self.bot_message_id = None
        self._build_updater()

    def _build_updater(self):
        self.updater = Updater(token=self.config['token'], use_context=True, request_kwargs=REQUEST_KWARGS)
        self._setup_handlers()

    def _setup_handlers(self):
        dp = self.updater.dispatcher
        dp.add_handler(CommandHandler('start', self.cmd_start))
        dp.add_handler(CommandHandler('get_rate', self.cmd_get_rate))
        dp.add_handler(CommandHandler('help', self.cmd_help))
        admin_filter = Filters.user(user_id=self.config['admins'])
        dp.add_handler(CommandHandler('users', self.cmd_users, filters=admin_filter))

    def get_rate_cached(self):
        now = time.time()
        if self.last_rates and (now - self.last_update_time < self.config['cache_ttl']):
            return self.last_rates
        self.last_rates = get_all_rates()
        self.last_update_time = now
        return self.last_rates

    def cmd_start(self, update: Update, context: CallbackContext):
        uid = str(update.effective_user.id)
        if uid not in self.users:
            self.users[uid] = {'username': update.effective_user.username, 'date': datetime.now().isoformat()}
            save_users(self.users)
        update.message.reply_text("Бот запущен. Жми /get_rate")

    def cmd_get_rate(self, update: Update, context: CallbackContext):
        text = self.get_rate_cached()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("ОБМЕН", url="https://telegra.ph/Obmen-11-06-2")]])
        # Отключаем предпросмотр здесь
        update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)

    def cmd_help(self, update: Update, context: CallbackContext):
        update.message.reply_text("/get_rate — курс\n/start — старт")

    def cmd_users(self, update: Update, context: CallbackContext):
        update.message.reply_text(f"Пользователей: {len(self.users)}")

    def periodic_update(self):
        while True:
            try:
                text = self.get_rate_cached()
                if self.config['channel_id']:
                    bot = self.updater.bot
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("ОБМЕН", url="https://telegra.ph/Obmen-11-06-2")]])
                    
                    if not self.bot_message_id:
                        # Отключаем превью при отправке нового сообщения
                        msg = bot.send_message(
                            chat_id=self.config['channel_id'], 
                            text=text, 
                            parse_mode="Markdown", 
                            reply_markup=kb, 
                            message_thread_id=int(self.config['topic_id']) if self.config['topic_id'] else None,
                            disable_web_page_preview=True
                        )
                        self.bot_message_id = msg.message_id
                        try:
                            bot.pin_chat_message(self.config['channel_id'], self.bot_message_id)
                        except: pass
                    else:
                        try:
                            # Отключаем превью при редактировании
                            bot.edit_message_text(
                                text=text, 
                                chat_id=self.config['channel_id'], 
                                message_id=self.bot_message_id, 
                                parse_mode="Markdown", 
                                reply_markup=kb,
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            if "Message is not modified" not in str(e):
                                logger.error(f"Ошибка правки: {e}")
                                self.bot_message_id = None
            except Exception as e:
                logger.error(f"Ошибка в цикле обновления: {e}")
            time.sleep(self.config['sleep_time'])

    def run(self):
        threading.Thread(target=self.periodic_update, daemon=True).start()
        self.updater.start_polling()
        self.updater.idle()

# --- СИСТЕМНЫЕ ФУНКЦИИ (LOCK) ---
def create_lock():
    """Проверяет наличие lock-файла и создает его, если бот не запущен"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            # Проверяем, реально ли процесс с таким PID живой
            if psutil.pid_exists(pid):
                print(f"⚠️ Ошибка: Бот уже запущен (PID {pid}).")
                logger.warning(f"Попытка повторного запуска отклонена. Бот уже работает под PID {pid}.")
                sys.exit(1)
            else:
                # Если файл есть, но процесса нет — удаляем "протухший" файл
                os.remove(LOCK_FILE)
        except (ValueError, OSError):
            os.remove(LOCK_FILE)

    # Записываем текущий PID в файл
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

if __name__ == '__main__':
    create_lock() # Теперь блокировка активна
    try:
        bot = CurrencyBot()
        bot.run()
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем.")
    finally:
        # При завершении работы удаляем файл, чтобы можно было запустить снова
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)