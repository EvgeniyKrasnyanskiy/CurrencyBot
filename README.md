# 💱 CurrencyBot - Современный Telegram бот для курсов валют

Современный Telegram-бот для отслеживания курса USDT/RUB с расширенной архитектурой, мониторингом и контейнеризацией.

## 🚀 Новые возможности

### ✨ Архитектурные улучшения
- **Модульная архитектура** - разделение на логические компоненты
- **Асинхронная обработка** - использование python-telegram-bot 20+
- **Конфигурация через dataclasses** - типобезопасная конфигурация
- **Абстрактные парсеры** - легко добавлять новые источники курсов
- **Система мониторинга** - Prometheus метрики и Grafana дашборды

### 🔧 Функциональные улучшения
- **Расширенная статистика пользователей** - активность, команды, регистрация
- **Система здоровья бота** - автоматическая проверка состояния
- **Улучшенное логирование** - структурированные логи с уровнями
- **Кеширование с TTL** - оптимизация запросов к API
- **Docker контейнеризация** - простое развертывание

### 📊 Мониторинг и метрики
- **Prometheus метрики** - команды, запросы, пользователи, ресурсы
- **Grafana дашборды** - визуализация метрик в реальном времени
- **Health checks** - автоматическая проверка здоровья системы
- **Системные метрики** - CPU, память, потоки, соединения

## 🏗 Архитектура

```
CurrencyBot/
├── config.py              # Конфигурация и валидация
├── exchange_rates.py      # Парсеры и сервис курсов валют
├── user_manager.py        # Управление пользователями
├── monitoring.py          # Мониторинг и метрики
├── modern_bot.py         # Основной асинхронный бот
├── currency_bot.py       # Старая версия (для совместимости)
├── tests/                # Тесты
├── monitoring/           # Конфигурация мониторинга
├── data/                 # Данные пользователей
├── logs/                 # Логи
└── docker-compose.yml    # Docker развертывание
```

## 🧰 Установка и запуск

### Быстрый старт с Docker

1. **Клонируйте репозиторий:**
```bash
git clone <repository-url>
cd CurrencyBot
```

2. **Создайте .env файл:**
```env
BOT_TOKEN=ваш_токен_бота
CHANNEL_ID=@ваш_канал
TOPIC_ID=123456789
ADMINS=["123456789"]
SLEEP_TIME=600
CACHE_TTL=300
```

3. **Запустите с Docker Compose:**
```bash
docker-compose up -d
```

### Локальная установка

1. **Установите зависимости:**
```bash
pip install -r requirements.txt
```

2. **Настройте переменные окружения** (см. выше)

3. **Запустите бота:**
```bash
python modern_bot.py
```

## 📡 Команды бота

### Пользовательские команды
- `/start` - регистрация и приветствие
- `/get_rate` - получить текущий курс USDT/RUB
- `/help` - справка по командам

### Админские команды
- `/setinterval <сек>` - изменить интервал обновления
- `/users` - список пользователей
- `/stats` - статистика бота
- `/cleanup` - очистка неактивных пользователей

## 🔍 Мониторинг

### Prometheus метрики
- `bot_commands_total` - количество команд по типам
- `exchange_request_duration_seconds` - время запросов к API
- `bot_active_users` - количество активных пользователей
- `bot_memory_usage_mb` - потребление памяти
- `bot_cpu_usage_percent` - нагрузка CPU

### Доступ к метрикам
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)
- **Метрики бота**: http://localhost:8000/metrics

## 🧪 Тестирование

```bash
# Запуск всех тестов
pytest

# Запуск с покрытием
pytest --cov=.

# Запуск конкретного теста
pytest tests/test_exchange_rates.py::TestCoinGeckoParser
```

## 🔧 Конфигурация

### Источники курсов валют
Настройте в `data/config.json`:
```json
{
    "urls": [
        "https://www.okx.com/ru-eu/convert/usdt-to-rub",
        "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
    ],
    "keywords": [
        "Сейчас USDT = ",
        "USDT/RUB"
    ]
}
```

### Переменные окружения
| Переменная | Описание | По умолчанию |
|------------|----------|---------------|
| `BOT_TOKEN` | Токен Telegram бота | - |
| `CHANNEL_ID` | ID канала для публикации | - |
| `TOPIC_ID` | ID топика (опционально) | - |
| `ADMINS` | JSON массив ID админов | `[]` |
| `SLEEP_TIME` | Интервал обновления (сек) | `600` |
| `CACHE_TTL` | Время жизни кеша (сек) | `300` |

## 🚀 Развертывание

### Docker Compose (рекомендуется)
```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f currency-bot

# Остановка
docker-compose down
```

### Docker
```bash
# Сборка образа
docker build -t currency-bot .

# Запуск контейнера
docker run -d \
  --name currency-bot \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  currency-bot
```

### Системный сервис
Создайте `/etc/systemd/system/currency-bot.service`:
```ini
[Unit]
Description=CurrencyBot Telegram Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/opt/currency-bot
Environment=PATH=/opt/currency-bot/venv/bin
ExecStart=/opt/currency-bot/venv/bin/python modern_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## 📈 Производительность

### Оптимизации
- **Кеширование** - TTL кеш для снижения нагрузки на API
- **Асинхронность** - неблокирующая обработка запросов
- **Connection pooling** - переиспользование HTTP соединений
- **Ленивая загрузка** - инициализация компонентов по требованию

### Мониторинг производительности
- Метрики Prometheus в реальном времени
- Grafana дашборды для анализа трендов
- Автоматические алерты при проблемах
- Логирование с уровнями детализации

## 🔒 Безопасность

### Меры безопасности
- **Контейнеризация** - изоляция процессов
- **Непривилегированный пользователь** - запуск от имени botuser
- **Переменные окружения** - безопасное хранение секретов
- **Валидация конфигурации** - проверка обязательных параметров
- **Обработка ошибок** - graceful degradation при сбоях

## 🤝 Вклад в проект

1. Fork репозитория
2. Создайте feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'Add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

## 📄 Лицензия

Этот проект распространяется под лицензией MIT. См. файл `LICENSE` для деталей.

## 🆘 Поддержка

- **Issues**: Создайте issue в GitHub
- **Discussions**: Используйте GitHub Discussions
- **Telegram**: @your_support_channel

---

**Сделано с ❤️ для сообщества криптотрейдеров**