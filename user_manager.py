import json
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from telegram import User

logger = logging.getLogger(__name__)

@dataclass
class UserData:
    """Модель данных пользователя"""
    id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    registration_date: str = ""
    last_activity: str = ""
    is_active: bool = True
    command_count: int = 0
    last_command: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UserData':
        return cls(**data)

class UserManager:
    """Менеджер пользователей"""
    
    def __init__(self, data_file: str = 'data/users.json'):
        self.data_file = data_file
        self.users: Dict[str, UserData] = {}
        self._load_users()
    
    def _load_users(self):
        """Загружает пользователей из файла"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                    self.users = {
                        user_id: UserData.from_dict(user_data)
                        for user_id, user_data in data.items()
                    }
                logger.info(f"Загружено {len(self.users)} пользователей")
            else:
                logger.info("Файл пользователей не найден, создаем новый")
        except Exception as e:
            logger.error(f"Ошибка загрузки пользователей: {e}")
            self.users = {}
    
    def _save_users(self):
        """Сохраняет пользователей в файл"""
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, 'w', encoding='utf-8-sig') as f:
                json.dump(
                    {user_id: user_data.to_dict() for user_id, user_data in self.users.items()},
                    f, indent=4, ensure_ascii=False
                )
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователей: {e}")
    
    def register_user(self, user: User) -> bool:
        """Регистрирует нового пользователя"""
        user_id = str(user.id)
        
        if user_id in self.users:
            # Обновляем существующего пользователя
            self.users[user_id].username = user.username or ""
            self.users[user_id].first_name = user.first_name or ""
            self.users[user_id].last_name = user.last_name or ""
            self.users[user_id].last_activity = datetime.now().isoformat()
            self.users[user_id].is_active = True
            logger.info(f"Обновлен пользователь: {user_id}")
        else:
            # Создаем нового пользователя
            self.users[user_id] = UserData(
                id=user.id,
                username=user.username or "",
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                registration_date=datetime.now().isoformat(),
                last_activity=datetime.now().isoformat()
            )
            logger.info(f"Зарегистрирован новый пользователь: {user_id}")
        
        self._save_users()
        return True
    
    def update_activity(self, user_id: int, command: str = ""):
        """Обновляет активность пользователя"""
        user_id_str = str(user_id)
        if user_id_str in self.users:
            self.users[user_id_str].last_activity = datetime.now().isoformat()
            self.users[user_id_str].command_count += 1
            if command:
                self.users[user_id_str].last_command = command
            self._save_users()
    
    def get_user(self, user_id: int) -> Optional[UserData]:
        """Получает данные пользователя"""
        return self.users.get(str(user_id))
    
    def get_active_users(self, days: int = 30) -> List[UserData]:
        """Получает активных пользователей за последние N дней"""
        cutoff_date = datetime.now() - timedelta(days=days)
        active_users = []
        
        for user_data in self.users.values():
            if user_data.is_active:
                try:
                    last_activity = datetime.fromisoformat(user_data.last_activity)
                    if last_activity > cutoff_date:
                        active_users.append(user_data)
                except ValueError:
                    continue
        
        return active_users
    
    def get_user_stats(self) -> Dict:
        """Получает статистику пользователей"""
        total_users = len(self.users)
        active_users = len(self.get_active_users())
        new_users_today = len([
            u for u in self.users.values()
            if datetime.fromisoformat(u.registration_date).date() == datetime.now().date()
        ])
        
        return {
            'total_users': total_users,
            'active_users': active_users,
            'new_users_today': new_users_today,
            'inactive_users': total_users - active_users
        }
    
    def get_users_summary(self) -> str:
        """Форматирует сводку пользователей"""
        stats = self.get_user_stats()
        active_users = self.get_active_users()
        
        summary = f"👥 Статистика пользователей:\n"
        summary += f"📊 Всего: {stats['total_users']}\n"
        summary += f"✅ Активных: {stats['active_users']}\n"
        summary += f"📈 Новых сегодня: {stats['new_users_today']}\n"
        summary += f"❌ Неактивных: {stats['inactive_users']}\n\n"
        
        if active_users:
            summary += "🔥 Топ активных пользователей:\n"
            # Сортируем по количеству команд
            top_users = sorted(active_users, key=lambda u: u.command_count, reverse=True)[:5]
            for i, user in enumerate(top_users, 1):
                name = user.first_name or user.username or f"User{user.id}"
                summary += f"{i}. {name} ({user.command_count} команд)\n"
        
        return summary
    
    def cleanup_inactive_users(self, days: int = 90) -> int:
        """Очищает неактивных пользователей"""
        cutoff_date = datetime.now() - timedelta(days=days)
        removed_count = 0
        
        user_ids_to_remove = []
        for user_id, user_data in self.users.items():
            try:
                last_activity = datetime.fromisoformat(user_data.last_activity)
                if last_activity < cutoff_date:
                    user_ids_to_remove.append(user_id)
            except ValueError:
                continue
        
        for user_id in user_ids_to_remove:
            del self.users[user_id]
            removed_count += 1
        
        if removed_count > 0:
            self._save_users()
            logger.info(f"Удалено {removed_count} неактивных пользователей")
        
        return removed_count 