import asyncio
import logging
import os
import sys
import time
from typing import Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    CallbackContext, filters
)
from telegram.error import TelegramError

from config import ConfigManager
from exchange_rates import ExchangeRateService
from user_manager import UserManager

# Настройка логирования
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    filename='logs/currency_bot.log',
    filemode='a',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

class ModernCurrencyBot:
    """Современная версия CurrencyBot с асинхронной архитектурой"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.config_manager.validate()
        
        self.bot_config = self.config_manager.bot_config
        self.exchange_config = self.config_manager.exchange_config
        
        # Инициализация сервисов
        self.exchange_service = ExchangeRateService(
            urls=self.exchange_config.urls,
            keywords=self.exchange_config.keywords,
            headers=self.exchange_config.headers
        )
        self.user_manager = UserManager()
        
        # Состояние бота
        self.last_message_id: Optional[int] = None
        self.is_running = False
        
        # Создание приложения
        self.application = Application.builder().token(self.bot_config.token).build()
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("get_rate", self.cmd_get_rate))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        
        # Админские команды
        admin_filter = filters.User(user_ids=self.bot_config.admins)
        self.application.add_handler(
            CommandHandler("setinterval", self.cmd_setinterval, filters=admin_filter)
        )
        self.application.add_handler(
            CommandHandler("users", self.cmd_users, filters=admin_filter)
        )
        self.application.add_handler(
            CommandHandler("stats", self.cmd_stats, filters=admin_filter)
        )
        self.application.add_handler(
            CommandHandler("cleanup", self.cmd_cleanup, filters=admin_filter)
        )
    
    def create_keyboard(self) -> InlineKeyboardMarkup:
        """Создает клавиатуру с кнопками"""
        keyboard = [
            [InlineKeyboardButton("💱 Обмен", url="https://telegra.ph/Obmen-11-06-2")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        if not user:
            return
        
        logger.info(f"/start от {user.id} @{user.username}")
        
        # Регистрируем пользователя
        self.user_manager.register_user(user)
        self.user_manager.update_activity(user.id, "start")
        
        welcome_text = (
            "🎉 Добро пожаловать в CurrencyBot!\n\n"
            "💱 Получайте актуальные курсы USDT/RUB\n"
            "📊 Отслеживайте изменения в реальном времени\n\n"
            "📌 Доступные команды:\n"
            "/get_rate — получить текущий курс\n"
            "/help — справка\n\n"
            "🚀 Начните с команды /get_rate"
        )
        
        await update.message.reply_text(welcome_text)
    
    async def cmd_get_rate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /get_rate"""
        user = update.effective_user
        if not user:
            return
        
        self.user_manager.update_activity(user.id, "get_rate")
        
        # Показываем "печатает..."
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action="typing"
        )
        
        try:
            # Получаем курс
            rate_text = self.exchange_service.get_cached_rate(self.bot_config.cache_ttl)
            keyboard = self.create_keyboard()
            
            await update.message.reply_text(
                rate_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
        except Exception as e:
            logger.error(f"Ошибка при получении курса: {e}")
            await update.message.reply_text(
                "❌ Ошибка при получении курса. Попробуйте позже."
            )
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_text = (
            "📌 Доступные команды:\n\n"
            "🔹 /start — регистрация и приветствие\n"
            "🔹 /get_rate — получить текущий курс USDT/RUB\n"
            "🔹 /help — эта справка\n\n"
            "🛠 Админские команды:\n"
            "🔹 /setinterval <сек> — изменить интервал обновления\n"
            "🔹 /users — список пользователей\n"
            "🔹 /stats — статистика бота\n"
            "🔹 /cleanup — очистка неактивных пользователей\n\n"
            "💡 Бот автоматически обновляет курс каждые "
            f"{self.bot_config.sleep_time // 60} минут"
        )
        
        await update.message.reply_text(help_text)
    
    async def cmd_setinterval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /setinterval (админ)"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Использование: /setinterval <секунд>\n"
                "Минимальный интервал: 60 секунд"
            )
            return
        
        try:
            interval = int(args[0])
            if interval < 60:
                await update.message.reply_text("❌ Интервал должен быть минимум 60 секунд")
                return
            
            self.bot_config.sleep_time = interval
            await update.message.reply_text(
                f"✅ Интервал обновления установлен: {interval} сек. "
                f"({interval // 60} мин.)"
            )
            logger.info(f"Админ изменил интервал: {interval}")
            
        except ValueError:
            await update.message.reply_text("❌ Введите корректное число")
    
    async def cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /users (админ)"""
        if not self.user_manager.users:
            await update.message.reply_text("👥 Нет зарегистрированных пользователей")
            return
        
        users_text = "👥 Список пользователей:\n\n"
        for user_id, user_data in list(self.user_manager.users.items())[:20]:  # Ограничиваем вывод
            name = user_data.first_name or user_data.username or f"User{user_data.id}"
            reg_date = datetime.fromisoformat(user_data.registration_date).strftime("%d.%m.%Y")
            users_text += f"• {name} (ID: {user_id})\n"
            users_text += f"  📅 Регистрация: {reg_date}\n"
            users_text += f"  📊 Команд: {user_data.command_count}\n\n"
        
        if len(self.user_manager.users) > 20:
            users_text += f"... и еще {len(self.user_manager.users) - 20} пользователей"
        
        await update.message.reply_text(users_text)
    
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats (админ)"""
        stats_text = self.user_manager.get_users_summary()
        await update.message.reply_text(stats_text)
    
    async def cmd_cleanup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /cleanup (админ)"""
        removed_count = self.user_manager.cleanup_inactive_users()
        await update.message.reply_text(
            f"🧹 Очистка завершена\n"
            f"Удалено неактивных пользователей: {removed_count}"
        )
    
    async def find_last_bot_message(self) -> Optional[int]:
        """Ищет последнее сообщение от бота в канале"""
        if self.last_message_id:
            return self.last_message_id
        
        try:
            chat = await self.application.bot.get_chat(self.bot_config.channel_id)
            
            if hasattr(chat, 'pinned_message') and chat.pinned_message:
                if (chat.pinned_message.from_user and
                    chat.pinned_message.from_user.id == (await self.application.bot.get_me()).id):
                    self.last_message_id = chat.pinned_message.message_id
                    logger.info(f"Найдено закрепленное сообщение: {self.last_message_id}")
                    return self.last_message_id
            return None
        except Exception as e:
            logger.error(f"Ошибка при поиске сообщения: {e}")
            return None
    
    async def send_or_edit_message(self, text: str):
        """Отправляет или редактирует сообщение в канале"""
        try:
            keyboard = self.create_keyboard()
            last_message_id = await self.find_last_bot_message()
            
            if last_message_id:
                try:
                    await self.application.bot.edit_message_text(
                        chat_id=self.bot_config.channel_id,
                        message_id=last_message_id,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                        disable_web_page_preview=True
                    )
                    logger.info("Сообщение с курсом обновлено")
                except TelegramError as e:
                    if "Message is not modified" in str(e):
                        logger.info("Курс не изменился — редактирование не требуется")
                    else:
                        logger.error(f"Ошибка при редактировании: {e}")
                        self.last_message_id = None
            else:
                message = await self.application.bot.send_message(
                    chat_id=self.bot_config.channel_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                    message_thread_id=int(self.bot_config.topic_id) if self.bot_config.topic_id else None
                )
                self.last_message_id = message.message_id
                
                try:
                    await self.application.bot.pin_chat_message(
                        chat_id=self.bot_config.channel_id,
                        message_id=message.message_id
                    )
                    logger.info("Сообщение отправлено и закреплено")
                except TelegramError as pin_error:
                    logger.warning(f"Не удалось закрепить: {pin_error}")
                    
        except Exception as e:
            logger.error(f"Ошибка при отправке/редактировании: {e}")
    
    async def periodic_update(self):
        """Периодическое обновление курса"""
        while self.is_running:
            try:
                if not self.bot_config.channel_id:
                    logger.warning("Не указан CHANNEL_ID")
                else:
                    text = self.exchange_service.get_cached_rate(self.bot_config.cache_ttl)
                    logger.info(f"Получен курс: {text}")
                    await self.send_or_edit_message(text)
                    
            except Exception as e:
                logger.error(f"Ошибка в periodic_update: {e}")
            
            await asyncio.sleep(self.bot_config.sleep_time)
    
    async def start(self):
        """Запуск бота"""
        logger.info("🚀 Запуск ModernCurrencyBot")
        self.is_running = True
        
        # Запускаем периодическое обновление в фоне
        asyncio.create_task(self.periodic_update())
        
        # Запускаем бота
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("✅ Бот запущен и готов к работе")
        
        # Ждем завершения
        try:
            await self.application.updater.idle()
        finally:
            await self.application.stop()
            await self.application.shutdown()
    
    async def stop(self):
        """Остановка бота"""
        logger.info("🛑 Остановка бота")
        self.is_running = False

async def main():
    """Главная функция"""
    print("📦 Запуск ModernCurrencyBot...")
    
    bot = ModernCurrencyBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n🛑 Получен сигнал остановки")
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        logger.error(f"Ошибка при запуске: {e}")
    finally:
        await bot.stop()

if __name__ == '__main__':
    asyncio.run(main()) 