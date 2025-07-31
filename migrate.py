#!/usr/bin/env python3
"""
Скрипт миграции со старой версии CurrencyBot на новую
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

def backup_old_data():
    """Создает резервную копию старых данных"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"backup_{timestamp}"
    
    print(f"📦 Создание резервной копии в {backup_dir}...")
    
    # Создаем директорию для бэкапа
    os.makedirs(backup_dir, exist_ok=True)
    
    # Копируем важные файлы
    files_to_backup = [
        'currency_bot.py',
        'data/users.json',
        'data/config.json',
        '.env'
    ]
    
    for file_path in files_to_backup:
        if os.path.exists(file_path):
            shutil.copy2(file_path, backup_dir)
            print(f"✅ Скопирован {file_path}")
    
    # Копируем логи
    if os.path.exists('logs'):
        shutil.copytree('logs', f"{backup_dir}/logs")
        print("✅ Скопированы логи")
    
    print(f"✅ Резервная копия создана: {backup_dir}")
    return backup_dir

def migrate_users_data():
    """Мигрирует данные пользователей в новый формат"""
    old_users_file = 'data/users.json'
    new_users_file = 'data/users_migrated.json'
    
    if not os.path.exists(old_users_file):
        print("⚠️ Файл пользователей не найден, пропускаем миграцию")
        return
    
    print("🔄 Миграция данных пользователей...")
    
    try:
        with open(old_users_file, 'r', encoding='utf-8-sig') as f:
            old_users = json.load(f)
        
        new_users = {}
        
        for user_id, user_data in old_users.items():
            # Преобразуем в новый формат
            new_user_data = {
                'id': int(user_id),
                'username': user_data.get('username', ''),
                'first_name': user_data.get('first_name', ''),
                'last_name': user_data.get('last_name', ''),
                'registration_date': user_data.get('registration_date', datetime.now().isoformat()),
                'last_activity': user_data.get('last_activity', datetime.now().isoformat()),
                'is_active': True,
                'command_count': 0,
                'last_command': ''
            }
            new_users[user_id] = new_user_data
        
        # Сохраняем в новый файл
        with open(new_users_file, 'w', encoding='utf-8') as f:
            json.dump(new_users, f, indent=4, ensure_ascii=False)
        
        print(f"✅ Мигрировано {len(new_users)} пользователей")
        
        # Переименовываем файлы
        shutil.move(old_users_file, f"{old_users_file}.old")
        shutil.move(new_users_file, old_users_file)
        
        print("✅ Файл пользователей обновлен")
        
    except Exception as e:
        print(f"❌ Ошибка миграции пользователей: {e}")

def migrate_config():
    """Мигрирует конфигурацию"""
    old_config_file = 'data/config.json'
    
    if not os.path.exists(old_config_file):
        print("⚠️ Файл конфигурации не найден, создаем новый...")
        create_default_config()
        return
    
    print("🔄 Миграция конфигурации...")
    
    try:
        with open(old_config_file, 'r', encoding='utf-8') as f:
            old_config = json.load(f)
        
        # Проверяем и дополняем конфигурацию
        new_config = {
            'urls': old_config.get('urls', [
                "https://www.okx.com/ru-eu/convert/usdt-to-rub",
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
            ]),
            'keywords': old_config.get('keywords', [
                "Сейчас USDT = ",
                "USDT/RUB"
            ])
        }
        
        # Сохраняем обновленную конфигурацию
        with open(old_config_file, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=4, ensure_ascii=False)
        
        print("✅ Конфигурация обновлена")
        
    except Exception as e:
        print(f"❌ Ошибка миграции конфигурации: {e}")

def create_default_config():
    """Создает конфигурацию по умолчанию"""
    default_config = {
        'urls': [
            "https://www.okx.com/ru-eu/convert/usdt-to-rub",
            "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
        ],
        'keywords': [
            "Сейчас USDT = ",
            "USDT/RUB"
        ]
    }
    
    os.makedirs('data', exist_ok=True)
    
    with open('data/config.json', 'w', encoding='utf-8') as f:
        json.dump(default_config, f, indent=4, ensure_ascii=False)
    
    print("✅ Создана конфигурация по умолчанию")

def create_directories():
    """Создает необходимые директории"""
    directories = [
        'logs',
        'data',
        'tests',
        'monitoring'
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✅ Создана директория: {directory}")

def create_env_template():
    """Создает шаблон .env файла"""
    env_template = """# Конфигурация CurrencyBot
BOT_TOKEN=your_bot_token_here
CHANNEL_ID=@your_channel_here
TOPIC_ID=123456789
ADMINS=["123456789"]
SLEEP_TIME=600
CACHE_TTL=300
"""
    
    if not os.path.exists('.env'):
        with open('.env', 'w', encoding='utf-8') as f:
            f.write(env_template)
        print("✅ Создан шаблон .env файла")
    else:
        print("⚠️ .env файл уже существует")

def check_dependencies():
    """Проверяет и устанавливает зависимости"""
    print("🔍 Проверка зависимостей...")
    
    try:
        import requests
        import telegram
        import psutil
        import prometheus_client
        print("✅ Все зависимости установлены")
    except ImportError as e:
        print(f"❌ Отсутствует зависимость: {e}")
        print("💡 Установите зависимости: pip install -r requirements.txt")

def main():
    """Основная функция миграции"""
    print("🚀 Запуск миграции CurrencyBot...")
    print("=" * 50)
    
    # Создаем резервную копию
    backup_dir = backup_old_data()
    
    # Создаем директории
    create_directories()
    
    # Мигрируем данные
    migrate_users_data()
    migrate_config()
    
    # Создаем шаблоны
    create_env_template()
    
    # Проверяем зависимости
    check_dependencies()
    
    print("=" * 50)
    print("✅ Миграция завершена!")
    print(f"📦 Резервная копия: {backup_dir}")
    print("\n📋 Следующие шаги:")
    print("1. Отредактируйте .env файл с вашими настройками")
    print("2. Установите зависимости: pip install -r requirements.txt")
    print("3. Запустите новый бот: python modern_bot.py")
    print("4. Или используйте Docker: docker-compose up -d")
    print("\n🔄 Старый бот сохранен как currency_bot.py (для совместимости)")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ Миграция прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Ошибка миграции: {e}")
        sys.exit(1) 