import re
import json
import requests
import logging
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

@dataclass
class ExchangeRate:
    """Модель курса валют"""
    source: str
    rate: float
    timestamp: float
    url: str
    raw_data: str = ""

class ExchangeRateParser(ABC):
    """Абстрактный класс для парсеров курсов"""
    
    @abstractmethod
    def can_parse(self, url: str, content_type: str, html: str) -> bool:
        """Проверяет, может ли парсер обработать данный источник"""
        pass
    
    @abstractmethod
    def parse(self, url: str, response: requests.Response) -> Optional[ExchangeRate]:
        """Парсит курс из ответа"""
        pass

class CoinGeckoParser(ExchangeRateParser):
    """Парсер для CoinGecko API"""
    
    def can_parse(self, url: str, content_type: str, html: str) -> bool:
        return "coingecko.com" in url and "application/json" in content_type
    
    def parse(self, url: str, response: requests.Response) -> Optional[ExchangeRate]:
        try:
            data = response.json()
            if "tether" in data and "rub" in data["tether"]:
                rate = float(data["tether"]["rub"])
                return ExchangeRate(
                    source="CoinGecko",
                    rate=rate,
                    timestamp=time.time(),
                    url=url,
                    raw_data=response.text
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Ошибка парсинга CoinGecko {url}: {e}")
        return None

class OKXParser(ExchangeRateParser):
    """Парсер для OKX"""
    
    def can_parse(self, url: str, content_type: str, html: str) -> bool:
        return "okx.com" in url
    
    def parse(self, url: str, response: requests.Response) -> Optional[ExchangeRate]:
        try:
            html = response.text
            patterns = [
                r'₽\s*(\d+[.,]?\d*)',
                r'(\d+[.,]?\d*)\s*₽',
                r'USDT.*?(\d+[.,]?\d*)\s*RUB',
                r'RUB.*?(\d+[.,]?\d*)\s*USDT'
            ]
            
            found_rates = []
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    try:
                        number = float(match.replace(",", "."))
                        if 70 < number < 85:  # Валидация разумного диапазона
                            found_rates.append(number)
                    except ValueError:
                        continue
            
            if found_rates:
                avg_rate = sum(found_rates) / len(found_rates)
                return ExchangeRate(
                    source="OKX",
                    rate=avg_rate,
                    timestamp=time.time(),
                    url=url,
                    raw_data=response.text
                )
        except Exception as e:
            logger.warning(f"Ошибка парсинга OKX {url}: {e}")
        return None

class GenericParser(ExchangeRateParser):
    """Универсальный парсер для других источников"""
    
    def __init__(self, keywords: List[str]):
        self.keywords = keywords
    
    def can_parse(self, url: str, content_type: str, html: str) -> bool:
        return True  # Универсальный парсер
    
    def parse(self, url: str, response: requests.Response) -> Optional[ExchangeRate]:
        try:
            html = response.text
            domain = url.split("//")[1].split("/")[0]
            
            # Поиск по ключевым словам
            for keyword in self.keywords:
                pattern = re.compile(
                    rf'{re.escape(keyword)}[\s:<>\-/a-zA-Z"\'=]*?(\d+[.,]?\d*)',
                    re.IGNORECASE
                )
                match = pattern.search(html)
                if match:
                    rate = float(match.group(1).replace(",", "."))
                    return ExchangeRate(
                        source=domain,
                        rate=rate,
                        timestamp=time.time(),
                        url=url,
                        raw_data=response.text
                    )
            
            # Fallback поиск по символу ₽
            soup = BeautifulSoup(html, 'html.parser')
            candidates = soup.find_all(string=re.compile(r'₽\s*\d+[.,]?\d*'))
            for s in candidates:
                match = re.search(r'₽\s*(\d+[.,]?\d*)', s)
                if match:
                    number = float(match.group(1).replace(",", "."))
                    if number > 20:
                        return ExchangeRate(
                            source=domain,
                            rate=number,
                            timestamp=time.time(),
                            url=url,
                            raw_data=response.text
                        )
        except Exception as e:
            logger.warning(f"Ошибка универсального парсинга {url}: {e}")
        return None

class ExchangeRateService:
    """Сервис для работы с курсами валют"""
    
    def __init__(self, urls: List[str], keywords: List[str], headers: Dict[str, str] = None):
        self.urls = urls
        self.keywords = keywords
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        # Инициализация парсеров
        self.parsers = [
            CoinGeckoParser(),
            OKXParser(),
            GenericParser(keywords)
        ]
    
    def fetch_rates(self) -> List[ExchangeRate]:
        """Получает курсы со всех источников"""
        rates = []
        
        for url in self.urls:
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                
                content_type = response.headers.get("Content-Type", "")
                html = response.text
                
                # Находим подходящий парсер
                for parser in self.parsers:
                    if parser.can_parse(url, content_type, html):
                        rate = parser.parse(url, response)
                        if rate:
                            rates.append(rate)
                            break
                else:
                    logger.warning(f"Не найден подходящий парсер для {url}")
                    
            except requests.RequestException as e:
                logger.error(f"Ошибка запроса {url}: {e}")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при обработке {url}: {e}")
        
        return rates
    
    def format_message(self, rates: List[ExchangeRate]) -> str:
        """Форматирует курсы в сообщение"""
        if not rates:
            return "⚠️ Не удалось получить курсы"
        
        # Группируем по источникам
        sources = {}
        for rate in rates:
            if rate.source not in sources:
                sources[rate.source] = []
            sources[rate.source].append(rate)
        
        # Формируем сообщение
        lines = []
        timestamp = time.strftime("%H:%M", time.localtime())
        
        # Приоритетные источники
        priority_sources = ["CoinGecko", "OKX"]
        priority_rates = []
        
        for source in priority_sources:
            if source in sources:
                avg_rate = sum(r.rate for r in sources[source]) / len(sources[source])
                priority_rates.append((source, avg_rate, sources[source][0].url))
        
        if len(priority_rates) >= 2:
            # Форматируем с двумя основными источниками
            cg_rate, okx_rate = None, None
            cg_url, okx_url = "", ""
            
            for source, rate, url in priority_rates:
                if source == "CoinGecko":
                    cg_rate = rate
                    cg_url = url
                elif source == "OKX":
                    okx_rate = rate
                    okx_url = url
            
            if cg_rate and okx_rate:
                cg_url_escaped = cg_url.replace("(", "\\(").replace(")", "\\)")
                okx_url_escaped = okx_url.replace("(", "\\(").replace(")", "\\)")
                return f"💵 USDT = ₽{cg_rate:.2f} ([CG]({cg_url_escaped})) и ₽{okx_rate:.2f} ([OKX]({okx_url_escaped})) {timestamp}"
        
        # Fallback - все источники
        for source, rate_list in sources.items():
            avg_rate = sum(r.rate for r in rate_list) / len(rate_list)
            lines.append(f"💱 {source}: {avg_rate:.2f}₽")
        
        lines.append(timestamp)
        return "\n".join(lines)
    
    def get_cached_rate(self, cache_ttl: int = 300) -> str:
        """Получает курс с кешированием"""
        current_time = time.time()
        
        # Проверяем кеш (упрощенная версия)
        if hasattr(self, '_last_rates') and hasattr(self, '_last_update_time'):
            if current_time - self._last_update_time < cache_ttl:
                # Обновляем только время в сообщении
                base_text = self._last_rates.split(' ')
                if len(base_text) >= 4:
                    new_text = ' '.join(base_text[:-1]) + ' ' + time.strftime("%H:%M", time.localtime())
                    return new_text
                return self._last_rates
        
        # Получаем новые курсы
        rates = self.fetch_rates()
        message = self.format_message(rates)
        
        # Сохраняем в кеш
        self._last_rates = message
        self._last_update_time = current_time
        
        return message 