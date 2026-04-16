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

# Константы для алертов
ALERT_INTERVALS = {
    "1ч": 3600,
    "4ч": 14400,
    "6ч": 21600,
    "12ч": 43200,
    "24ч": 86400
}
ALERT_THRESHOLDS = {
    "1ч": 2.0,
    "4ч": 3.0,
    "6ч": 4.0,
    "12ч": 5.0,
    "24ч": 6.0
}

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
    try:
        with open('data/users.json', 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}

def save_users(users):
    os.makedirs('data', exist_ok=True)
    with open('data/users.json', 'w', encoding='utf-8-sig') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

def load_bot_state():
    if not os.path.exists('data/bot_state.json'): return {"last_message_id": None}
    try:
        with open('data/bot_state.json', 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {"last_message_id": None}

def save_bot_state(message_id):
    os.makedirs('data', exist_ok=True)
    with open('data/bot_state.json', 'w') as f:
        json.dump({"last_message_id": message_id}, f)

# --- КОРНЕВАЯ ЛОГИКА КУРСОВ ---
def get_all_rates(history_r, history_c):
    headers = {"User-Agent": "Mozilla/5.0"}
    url_link_cg = "https://www.coingecko.com/en/coins/tether/rub"
    url_link_rapira = "https://rapira.net/exchange/USDT_RUB"
    timestamp = datetime.now().strftime("%H:%M")
    
    usdt_CG_val, usdt_Rapira_val = None, None
    res_r, res_c = "???", "???"

    to_time = int(time.time() * 1000)
    from_time = to_time - (24 * 60 * 60 * 1000)

    # 1. Rapira
    try:
        url_rapira = f"https://api.rapira.net/market/history?symbol=USDT/RUB&from={from_time}&to={to_time}&resolution=15"
        r = requests.get(url_rapira, headers=headers, timeout=10, proxies=PROXY_DICT)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            curr_r = float(data[-1][4])
            usdt_Rapira_val = curr_r
            diff_str = ""
            if history_r:
                prev_r = history_r[-1][1]
                diff = ((curr_r - prev_r) / prev_r) * 100
                if abs(diff) >= 1.0:
                    diff_str = f" ({'+' if diff > 0 else ''}{diff:.2f}%)"
            res_r = f"[{curr_r:.2f}{diff_str}]({url_link_rapira})"
    except Exception as e: logger.error(f"Rapira Error: {e}")

    # 2. CoinGecko
    try:
        url_cg = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
        r = requests.get(url_cg, headers=headers, timeout=10, proxies=PROXY_DICT)
        if r.status_code == 200:
            curr_c = float(r.json()['tether']['rub'])
            usdt_CG_val = curr_c
            diff_str = ""
            if history_c:
                prev_c = history_c[-1][1]
                diff = ((curr_c - prev_c) / prev_c) * 100
                if abs(diff) >= 1.0:
                    diff_str = f" ({'+' if diff > 0 else ''}{diff:.2f}%)"
            res_c = f"[{curr_c:.2f}{diff_str}]({url_link_cg})"
    except Exception as e: logger.error(f"CG Error: {e}")

    msg = f"💵 USDt = ₽{res_r} и ₽{res_c} в {timestamp}"
    return msg, usdt_Rapira_val, usdt_CG_val

# --- BOT CLASS ---
class CurrencyBot:
    def __init__(self):
        self.config = load_env_config()
        self.users = load_users()
        
        # Загружаем ID сообщения из файла при старте
        state = load_bot_state()
        self.bot_message_id = state.get("last_message_id")
        
        self.last_rates = ""
        self.last_update_time = 0
        self.history_r = []
        self.history_c = []
        self.sent_alerts = {}
        
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
        
        text, val_r, val_c = get_all_rates(self.history_r, self.history_c)
        
        # Обновляем историю если данные получены
        if val_r:
            self.history_r.append((now, val_r))
            self.history_r = [(t, p) for t, p in self.history_r if t > now - 86400]
        if val_c:
            self.history_c.append((now, val_c))
            self.history_c = [(t, p) for t, p in self.history_c if t > now - 86400]

        self.last_rates = text
        self.last_update_time = now
        return self.last_rates

    def check_volatility_alerts(self, current_val, history, label):
        if not history or not current_val: return None
        now = time.time()
        triggered = []
        for period, secs in ALERT_INTERVALS.items():
            threshold = ALERT_THRESHOLDS[period]
            target_t = now - secs
            # Ищем самую старую запись в пределах нужного окна
            past_entry = next((p for t, p in reversed(history) if t <= target_t), None)
            if past_entry:
                diff = ((current_val - past_entry) / past_entry) * 100
                if abs(diff) >= threshold:
                    triggered.append(f"• {label} за {period}: *{'+' if diff > 0 else ''}{diff:.2f}%*")
        return "\n".join(triggered) if triggered else None

    def cmd_start(self, update: Update, context: CallbackContext):
        uid = str(update.effective_user.id)
        if uid not in self.users:
            self.users[uid] = {'username': update.effective_user.username, 'date': datetime.now().isoformat()}
            save_users(self.users)
        update.message.reply_text("Бот запущен. Жми /get_rate")

    def cmd_get_rate(self, update: Update, context: CallbackContext):
        text = self.get_rate_cached()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("ОБМЕН", url="https://telegra.ph/Obmen-11-06-2")]])
        update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)

    def cmd_help(self, update: Update, context: CallbackContext):
        update.message.reply_text("/get_rate — курс\n/start — старт")

    def cmd_users(self, update: Update, context: CallbackContext):
        update.message.reply_text(f"Пользователей: {len(self.users)}")

    def periodic_update(self):
        # Настройки "тишины"
        alert_cooldown = 3000  # 50 минут в секундах
        
        while True:
            try:
                # 1. Получаем свежий курс (обновляет историю внутри get_rate_cached)
                text = self.get_rate_cached()
                bot = self.updater.bot
                now = time.time()
                
                # 2. Проверка алертов
                curr_r = self.history_r[-1][1] if self.history_r else None
                curr_c = self.history_c[-1][1] if self.history_c else None
                
                new_alerts = []
                for label, val, history in [("Rapira", curr_r, self.history_r), ("CoinGecko", curr_c, self.history_c)]:
                    alert_text = self.check_volatility_alerts(val, history, label)
                    
                    if alert_text:
                        alert_key = f"{label}_{alert_text}"
                        last_sent = self.sent_alerts.get(alert_key, 0)
                        if now - last_sent > alert_cooldown:
                            new_alerts.append(alert_text)
                            self.sent_alerts[alert_key] = now

                # 3. Отправка алертов (новым сообщением)
                if new_alerts:
                    combined_text = "\n".join(new_alerts)
                    try:
                        bot.send_message(
                            chat_id=self.config['channel_id'], 
                            text=f"🚨 *ВНИМАНИЕ: ВОЛАТИЛЬНОСТЬ!*\n\n{combined_text}", 
                            parse_mode="Markdown",
                            message_thread_id=int(self.config['topic_id']) if self.config['topic_id'] else None
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки алерта: {e}")

                self.sent_alerts = {k: v for k, v in self.sent_alerts.items() if now - v < 86400}

                # 4. Обновление закрепленного сообщения
                if self.config['channel_id']:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("ОБМЕН", url="https://telegra.ph/Obmen-11-06-2")]])
                    
                    if not self.bot_message_id:
                        # Отправляем новое сообщение
                        msg = bot.send_message(
                            chat_id=self.config['channel_id'], 
                            text=text, 
                            parse_mode="Markdown", 
                            reply_markup=kb, 
                            message_thread_id=int(self.config['topic_id']) if self.config['topic_id'] else None,
                            disable_web_page_preview=True
                        )
                        self.bot_message_id = msg.message_id
                        save_bot_state(self.bot_message_id) # Запоминаем в файл
                        try:
                            bot.pin_chat_message(self.config['channel_id'], self.bot_message_id)
                        except: pass
                    else:
                        # Пытаемся редактировать существующее
                        try:
                            bot.edit_message_text(
                                text=text, 
                                chat_id=self.config['channel_id'], 
                                message_id=self.bot_message_id, 
                                parse_mode="Markdown", 
                                reply_markup=kb,
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            error_msg = str(e)
                            # Если сообщение не найдено (удалено) — сбрасываем везде
                            if "Message to edit not found" in error_msg or "Message_id_invalid" in error_msg:
                                self.bot_message_id = None
                                save_bot_state(None) # Сбрасываем в файле
                                logger.warning("Закреп не найден, ID сброшен для пересоздания.")
                            elif "Message is not modified" not in error_msg:
                                logger.error(f"Ошибка правки закрепа: {e}")

            except Exception as e:
                logger.error(f"Критическая ошибка в periodic_update: {e}")
            
            time.sleep(self.config['sleep_time'])

    def run(self):
        threading.Thread(target=self.periodic_update, daemon=True).start()
        self.updater.start_polling()
        self.updater.idle()

def create_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                print(f"⚠️ Ошибка: Бот уже запущен (PID {pid}).")
                sys.exit(1)
            else: os.remove(LOCK_FILE)
        except: os.remove(LOCK_FILE)
    with open(LOCK_FILE, 'w') as f: f.write(str(os.getpid()))

if __name__ == '__main__':
    create_lock()
    try:
        bot = CurrencyBot()
        bot.run()
    except KeyboardInterrupt:
        print("\nБот остановлен.")
    finally:
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)