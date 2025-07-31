import os
import json
from dataclasses import dataclass
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class BotConfig:
    """Конфигурация бота"""
    token: str
    channel_id: str
    topic_id: Optional[str] = None
    admins: List[int] = None
    sleep_time: int = 600
    cache_ttl: int = 300
    
    def __post_init__(self):
        if self.admins is None:
            self.admins = []

@dataclass
class ExchangeConfig:
    """Конфигурация источников курсов"""
    urls: List[str]
    keywords: List[str]
    headers: Dict[str, str] = None
    
    def __post_init__(self):
        if self.headers is None:
            self.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

class ConfigManager:
    """Менеджер конфигурации"""
    
    def __init__(self):
        self.bot_config = self._load_bot_config()
        self.exchange_config = self._load_exchange_config()
    
    def _load_bot_config(self) -> BotConfig:
        """Загрузка конфигурации бота из .env"""
        admins_str = os.getenv('ADMINS', '[]')
        try:
            admins = json.loads(admins_str)
        except json.JSONDecodeError:
            admins = []
        
        return BotConfig(
            token=os.getenv('BOT_TOKEN'),
            channel_id=os.getenv('CHANNEL_ID'),
            topic_id=os.getenv('TOPIC_ID'),
            admins=admins,
            sleep_time=int(os.getenv('SLEEP_TIME', '600')),
            cache_ttl=int(os.getenv('CACHE_TTL', '300'))
        )
    
    def _load_exchange_config(self) -> ExchangeConfig:
        """Загрузка конфигурации источников курсов"""
        config_file = 'data/config.json'
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return ExchangeConfig(
                    urls=data.get('urls', []),
                    keywords=data.get('keywords', [])
                )
        
        # Fallback конфигурация
        return ExchangeConfig(
            urls=[
                "https://www.okx.com/ru-eu/convert/usdt-to-rub",
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
            ],
            keywords=["Сейчас USDT = "]
        )
    
    def validate(self) -> bool:
        """Валидация конфигурации"""
        if not self.bot_config.token:
            raise ValueError("BOT_TOKEN не указан в .env")
        if not self.bot_config.channel_id:
            raise ValueError("CHANNEL_ID не указан в .env")
        if not self.exchange_config.urls:
            raise ValueError("Не указаны URL источников курсов")
        return True 