import pytest
import time
from unittest.mock import Mock, patch
from exchange_rates import (
    ExchangeRate, CoinGeckoParser, OKXParser, 
    GenericParser, ExchangeRateService
)

class TestExchangeRate:
    """Тесты для модели ExchangeRate"""
    
    def test_exchange_rate_creation(self):
        """Тест создания объекта ExchangeRate"""
        rate = ExchangeRate(
            source="Test",
            rate=75.5,
            timestamp=time.time(),
            url="https://test.com"
        )
        
        assert rate.source == "Test"
        assert rate.rate == 75.5
        assert rate.url == "https://test.com"
        assert rate.raw_data == ""

class TestCoinGeckoParser:
    """Тесты для парсера CoinGecko"""
    
    def test_can_parse_coingecko(self):
        """Тест определения возможности парсинга CoinGecko"""
        parser = CoinGeckoParser()
        
        # Правильный URL и content-type
        assert parser.can_parse(
            "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub",
            "application/json",
            ""
        )
        
        # Неправильный URL
        assert not parser.can_parse(
            "https://okx.com/api",
            "application/json",
            ""
        )
        
        # Неправильный content-type
        assert not parser.can_parse(
            "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub",
            "text/html",
            ""
        )
    
    def test_parse_coingecko_success(self):
        """Тест успешного парсинга CoinGecko"""
        parser = CoinGeckoParser()
        
        # Мокаем response
        mock_response = Mock()
        mock_response.json.return_value = {"tether": {"rub": 78.5}}
        mock_response.text = '{"tether": {"rub": 78.5}}'
        
        result = parser.parse("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub", mock_response)
        
        assert result is not None
        assert result.source == "CoinGecko"
        assert result.rate == 78.5
        assert result.url == "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
    
    def test_parse_coingecko_failure(self):
        """Тест неудачного парсинга CoinGecko"""
        parser = CoinGeckoParser()
        
        # Мокаем response с неправильными данными
        mock_response = Mock()
        mock_response.json.return_value = {"wrong": "data"}
        mock_response.text = '{"wrong": "data"}'
        
        result = parser.parse("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub", mock_response)
        
        assert result is None

class TestOKXParser:
    """Тесты для парсера OKX"""
    
    def test_can_parse_okx(self):
        """Тест определения возможности парсинга OKX"""
        parser = OKXParser()
        
        # Правильный URL
        assert parser.can_parse("https://www.okx.com/ru-eu/convert/usdt-to-rub", "", "")
        
        # Неправильный URL
        assert not parser.can_parse("https://coingecko.com/api", "", "")
    
    def test_parse_okx_success(self):
        """Тест успешного парсинга OKX"""
        parser = OKXParser()
        
        # Мокаем response с HTML содержащим курс
        mock_response = Mock()
        mock_response.text = """
        <html>
            <body>
                <div>USDT = 79.50 ₽</div>
                <span>₽ 78.25</span>
            </body>
        </html>
        """
        
        result = parser.parse("https://www.okx.com/ru-eu/convert/usdt-to-rub", mock_response)
        
        assert result is not None
        assert result.source == "OKX"
        assert 78.0 <= result.rate <= 80.0  # Проверяем разумный диапазон
    
    def test_parse_okx_no_rate(self):
        """Тест парсинга OKX без курса"""
        parser = OKXParser()
        
        # Мокаем response без курса
        mock_response = Mock()
        mock_response.text = "<html><body>No rate here</body></html>"
        
        result = parser.parse("https://www.okx.com/ru-eu/convert/usdt-to-rub", mock_response)
        
        assert result is None

class TestGenericParser:
    """Тесты для универсального парсера"""
    
    def test_can_parse_generic(self):
        """Тест определения возможности парсинга универсальным парсером"""
        parser = GenericParser(["USDT = "])
        
        # Универсальный парсер может парсить любой URL
        assert parser.can_parse("https://any-site.com", "", "")
    
    def test_parse_generic_with_keyword(self):
        """Тест парсинга с ключевым словом"""
        parser = GenericParser(["USDT = "])
        
        mock_response = Mock()
        mock_response.text = """
        <html>
            <body>
                <div>USDT = 77.80 ₽</div>
            </body>
        </html>
        """
        
        result = parser.parse("https://test-site.com", mock_response)
        
        assert result is not None
        assert result.source == "test-site.com"
        assert result.rate == 77.80
    
    def test_parse_generic_fallback(self):
        """Тест fallback парсинга по символу ₽"""
        parser = GenericParser([])  # Без ключевых слов
        
        mock_response = Mock()
        mock_response.text = """
        <html>
            <body>
                <div>Курс: ₽ 76.45</div>
            </body>
        </html>
        """
        
        result = parser.parse("https://test-site.com", mock_response)
        
        assert result is not None
        assert result.source == "test-site.com"
        assert result.rate == 76.45

class TestExchangeRateService:
    """Тесты для сервиса курсов валют"""
    
    def test_service_initialization(self):
        """Тест инициализации сервиса"""
        urls = ["https://test1.com", "https://test2.com"]
        keywords = ["USDT = "]
        
        service = ExchangeRateService(urls, keywords)
        
        assert service.urls == urls
        assert service.keywords == keywords
        assert len(service.parsers) == 3  # CoinGecko, OKX, Generic
    
    @patch('exchange_rates.requests.get')
    def test_fetch_rates_success(self, mock_get):
        """Тест успешного получения курсов"""
        # Мокаем успешный ответ
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers.get.return_value = "application/json"
        mock_response.json.return_value = {"tether": {"rub": 78.5}}
        mock_response.text = '{"tether": {"rub": 78.5}}'
        
        mock_get.return_value = mock_response
        
        service = ExchangeRateService(
            urls=["https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"],
            keywords=[]
        )
        
        rates = service.fetch_rates()
        
        assert len(rates) == 1
        assert rates[0].source == "CoinGecko"
        assert rates[0].rate == 78.5
    
    @patch('exchange_rates.requests.get')
    def test_fetch_rates_failure(self, mock_get):
        """Тест неудачного получения курсов"""
        # Мокаем ошибку запроса
        mock_get.side_effect = Exception("Network error")
        
        service = ExchangeRateService(
            urls=["https://test.com"],
            keywords=[]
        )
        
        rates = service.fetch_rates()
        
        assert len(rates) == 0
    
    def test_format_message_with_rates(self):
        """Тест форматирования сообщения с курсами"""
        service = ExchangeRateService([], [])
        
        # Создаем тестовые курсы
        rates = [
            ExchangeRate("CoinGecko", 78.5, time.time(), "https://coingecko.com"),
            ExchangeRate("OKX", 79.2, time.time(), "https://okx.com")
        ]
        
        message = service.format_message(rates)

        # Проверяем, что сообщение содержит курсы (формат может быть разным)
        assert "78.50" in message or "78.5" in message
        assert "79.20" in message or "79.2" in message
        assert "USDT" in message
    
    def test_format_message_no_rates(self):
        """Тест форматирования сообщения без курсов"""
        service = ExchangeRateService([], [])
        
        message = service.format_message([])
        
        assert "Не удалось получить курсы" in message
    
    def test_get_cached_rate(self):
        """Тест получения курса с кешированием"""
        service = ExchangeRateService([], [])
        
        # Первый вызов должен получить новые данные
        with patch.object(service, 'fetch_rates') as mock_fetch:
            mock_fetch.return_value = [
                ExchangeRate("Test", 75.0, time.time(), "https://test.com")
            ]
            
            result1 = service.get_cached_rate(cache_ttl=1)
            result2 = service.get_cached_rate(cache_ttl=1)
            
            # Второй вызов должен использовать кеш
            assert mock_fetch.call_count == 1
            assert result1 == result2

if __name__ == "__main__":
    pytest.main([__file__]) 