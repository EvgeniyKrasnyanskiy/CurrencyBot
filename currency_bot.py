import os
import re
import json
import time
import logging
from logging.handlers import RotatingFileHandler
import threading
import psutil
import sys
import signal
import subprocess
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, Filters, MessageHandler
from telegram.error import NetworkError, RetryAfter, TimedOut
from moderation import ModerationManager

load_dotenv()

# --- CONFIG & PROXY ---
USE_PROXY = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "10808"))

if USE_PROXY:
    REQUEST_KWARGS = {'proxy_url': f'http://{PROXY_HOST}:{PROXY_PORT}/', 'connect_timeout': 30, 'read_timeout': 30}
    PROXY_DICT = {"http": f"http://{PROXY_HOST}:{PROXY_PORT}", "https": f"http://{PROXY_HOST}:{PROXY_PORT}"}
else:
    REQUEST_KWARGS = {'connect_timeout': 30, 'read_timeout': 30}
    PROXY_DICT = None

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

# Logging with automatic rotation (max 5MB per file, up to 3 archives)
os.makedirs('logs', exist_ok=True)
bot_log_handler = RotatingFileHandler(
    os.path.join('logs', 'currency_bot.log'),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8'
)
bot_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[bot_log_handler])
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

    now_dt = datetime.now()
    timestamp = now_dt.strftime("%H:%M")
    date_str = now_dt.strftime("%d.%m")

    # Начало текущих суток для расчета % за день
    start_of_day = datetime(now_dt.year, now_dt.month, now_dt.day).timestamp()

    usdt_CG_val, usdt_Rapira_val = None, None
    res_r, res_c = "???", "???"
    day_diff_r, day_diff_c = "", ""

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

            arrow = ""
            if history_r:
                # Стрелка (по сравнению с последним кэшем)
                prev_r = history_r[-1][1]
                if curr_r > prev_r:
                    arrow = "⬈"
                elif curr_r < prev_r:
                    arrow = "⬊"
                else:
                    arrow = "→"

                # Процент за день (с 00:00)
                first_today = next((p for t, p in history_r if t >= start_of_day), history_r[0][1])
                diff_pct = ((curr_r - first_today) / first_today) * 100
                day_diff_r = f"{'+' if diff_pct > 0 else ''}{diff_pct:.2f}% (Rap)"

            res_r = f"[{curr_r:.2f}{arrow}]({url_link_rapira})"
    except Exception as e:
        logger.error(f"Rapira Error: {e}")

    # 2. CoinGecko
    try:
        url_cg = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
        r = requests.get(url_cg, headers=headers, timeout=10, proxies=PROXY_DICT)
        if r.status_code == 200:
            curr_c = float(r.json()['tether']['rub'])
            usdt_CG_val = curr_c

            arrow = ""
            if history_c:
                # Стрелка
                prev_c = history_c[-1][1]
                if curr_c > prev_c:
                    arrow = "⬈"
                elif curr_c < prev_c:
                    arrow = "⬊"
                else:
                    arrow = "→"

                # Процент за день (с 00:00)
                first_today = next((p for t, p in history_c if t >= start_of_day), history_c[0][1])
                diff_pct = ((curr_c - first_today) / first_today) * 100
                day_diff_c = f"{'+' if diff_pct > 0 else ''}{diff_pct:.2f}% (CG)"

            res_c = f"[{curr_c:.2f}{arrow}]({url_link_cg})"
    except Exception as e:
        logger.error(f"CG Error: {e}")

    # Формируем итоговое сообщение
    msg = rf"💵 USDt = ₽{res_r} | ₽{res_c} \[{timestamp}]"

    if day_diff_r or day_diff_c:
        msg += f"\n\n📈 {date_str}: {day_diff_r} | {day_diff_c}"

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
        self.moderation = ModerationManager()
        
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
        dp.add_handler(CommandHandler('post_rules', self.cmd_post_rules, filters=admin_filter))

        # Moderation handlers (group 1 so they don't interfere with command handling)
        dp.add_handler(
            MessageHandler(Filters.all & ~Filters.update.edited_message, self.moderation.handle_message),
            group=1
        )
        dp.add_handler(
            MessageHandler(Filters.update.edited_message, self.moderation.handle_edited_message),
            group=1
        )

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

    def cmd_post_rules(self, update: Update, context: CallbackContext):
        success = self.moderation.send_welcome_rules_if_needed(context.bot, force=True)
        if success:
            update.message.reply_text("✅ Правила успешно опубликованы в топике «Обмен».")
        else:
            update.message.reply_text("⚠️ Ошибка публикации правил. Проверьте logs/moderation.log")

    def _send_and_pin_rate_message(self, bot, text, kb):
        """Send a new rates message to the channel/topic, pin it, and persist state."""
        try:
            msg = bot.send_message(
                chat_id=self.config['channel_id'],
                text=text,
                parse_mode="Markdown",
                reply_markup=kb,
                message_thread_id=int(self.config['topic_id']) if self.config['topic_id'] else None,
                disable_web_page_preview=True
            )
            self.bot_message_id = msg.message_id
            save_bot_state(self.bot_message_id)
            logger.info(f"Отправлено новое сообщение с курсом (ID: {self.bot_message_id}).")
            try:
                bot.pin_chat_message(self.config['channel_id'], self.bot_message_id)
                logger.info(f"Сообщение {self.bot_message_id} успешно закреплено.")
            except Exception as pin_err:
                logger.warning(f"Не удалось закрепить сообщение {self.bot_message_id}: {pin_err}")
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки нового закрепленного сообщения: {e}")
            return False

    def update_pinned_rate_message(self, bot, text):
        """Update existing pinned rates message or immediately create and pin a new one if missing/deleted."""
        if not self.config['channel_id']:
            return

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("ОБМЕН", url="https://telegra.ph/Obmen-11-06-2")]])

        # If ID is unknown, check if a pinned message from this bot already exists in the channel/topic
        if not self.bot_message_id:
            try:
                chat = bot.get_chat(self.config['channel_id'])
                pinned = getattr(chat, 'pinned_message', None)
                if pinned and pinned.from_user and pinned.from_user.id == bot.id:
                    target_thread = int(self.config['topic_id']) if self.config['topic_id'] else None
                    if target_thread is None or pinned.message_thread_id == target_thread:
                        self.bot_message_id = pinned.message_id
                        save_bot_state(self.bot_message_id)
                        logger.info(f"Обнаружен существующий закреп бота: {self.bot_message_id}")
            except Exception as e:
                logger.debug(f"Не удалось проверить текущий закреп чата: {e}")

        # If still no message ID, create and pin new
        if not self.bot_message_id:
            self._send_and_pin_rate_message(bot, text, kb)
            return

        # Attempt to edit existing message
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
            error_lower = error_msg.lower()
            if "message is not modified" in error_lower:
                pass
            elif any(s in error_lower for s in ["not found", "invalid", "can't be edited", "cant be edited", "deleted"]):
                logger.warning(f"Закреп {self.bot_message_id} не найден или удален ({e}). Немедленно создаем новый...")
                self.bot_message_id = None
                save_bot_state(None)
                # Immediately send and pin without waiting for next cycle
                self._send_and_pin_rate_message(bot, text, kb)
            else:
                logger.error(f"Ошибка правки закрепа {self.bot_message_id}: {e}")

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
                self.update_pinned_rate_message(bot, text)

            except Exception as e:
                logger.error(f"Критическая ошибка в periodic_update: {e}")
            
            time.sleep(self.config['sleep_time'])

    def _delayed_welcome_rules(self):
        time.sleep(3)
        self.moderation.send_welcome_rules_if_needed(self.updater.bot)

    def run(self):
        commit = get_git_commit_hash()
        pid = os.getpid()
        mod_status = "Enabled" if self.moderation.config.enabled else "Disabled"
        start_banner = (
            f"🚀 CurrencyBot started | PID: {pid} | Commit: {commit} | "
            f"TargetChat: {self.config['channel_id']} | Topic: {self.config['topic_id']} | Moderation: {mod_status}"
        )
        logger.info("=" * 70)
        logger.info(start_banner)
        logger.info("=" * 70)
        print(start_banner, flush=True)

        # Post rules in background after polling is initialized
        threading.Thread(target=self._delayed_welcome_rules, daemon=True).start()
        threading.Thread(target=self.periodic_update, daemon=True).start()
        self.updater.start_polling()
        self.updater.idle()


def get_git_commit_hash() -> str:
    """Safely retrieve short git commit hash or 'unknown'."""
    try:
        res = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def create_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                print(f"⚠️ Ошибка: Бот уже запущен (PID {pid}).", flush=True)
                sys.exit(1)
            else:
                os.remove(LOCK_FILE)
        except Exception:
            os.remove(LOCK_FILE)
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def handle_exit(signum, frame):
    pid = os.getpid()
    logger.info(f"🛑 Received signal {signum}. Stopping CurrencyBot (PID {pid})...")
    print(f"\n🛑 Stopping CurrencyBot (PID {pid}, signal {signum})...", flush=True)
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, handle_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_exit)

    create_lock()
    try:
        bot = CurrencyBot()
        bot.run()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.error(f"💥 Unhandled fatal error: {e}", exc_info=True)
        print(f"💥 Fatal error: {e}", flush=True)
    finally:
        if os.path.exists(LOCK_FILE):
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass
        logger.info(f"🛑 CurrencyBot (PID {os.getpid()}) shutdown complete.")
        print(f"🛑 CurrencyBot (PID {os.getpid()}) shutdown complete.", flush=True)