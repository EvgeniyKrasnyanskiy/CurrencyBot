import time
import logging
import psutil
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

@dataclass
class BotMetrics:
    """Метрики бота"""
    uptime_seconds: float
    memory_usage_mb: float
    cpu_usage_percent: float
    total_commands: int
    successful_requests: int
    failed_requests: int
    active_users: int
    total_users: int

class MonitoringService:
    """Сервис мониторинга и метрик"""
    
    def __init__(self, port: int = 8000):
        self.start_time = time.time()
        self.port = port
        
        # Prometheus метрики
        self.command_counter = Counter('bot_commands_total', 'Total bot commands', ['command'])
        self.request_duration = Histogram('exchange_request_duration_seconds', 'Exchange request duration')
        self.active_users_gauge = Gauge('bot_active_users', 'Number of active users')
        self.total_users_gauge = Gauge('bot_total_users', 'Total number of users')
        self.memory_gauge = Gauge('bot_memory_usage_mb', 'Memory usage in MB')
        self.cpu_gauge = Gauge('bot_cpu_usage_percent', 'CPU usage percentage')
        
        # Статистика
        self.stats = {
            'commands': {},
            'requests': {'success': 0, 'failed': 0},
            'start_time': self.start_time
        }
        
        # Запускаем HTTP сервер для метрик
        try:
            start_http_server(port)
            logger.info(f"📊 Метрики доступны на порту {port}")
        except Exception as e:
            logger.warning(f"Не удалось запустить сервер метрик: {e}")
    
    def record_command(self, command: str):
        """Записывает выполнение команды"""
        self.command_counter.labels(command=command).inc()
        
        if command not in self.stats['commands']:
            self.stats['commands'][command] = 0
        self.stats['commands'][command] += 1
        
        logger.debug(f"Команда записана: {command}")
    
    def record_request(self, success: bool, duration: float):
        """Записывает результат запроса к API"""
        self.request_duration.observe(duration)
        
        if success:
            self.stats['requests']['success'] += 1
        else:
            self.stats['requests']['failed'] += 1
    
    def update_user_metrics(self, active_users: int, total_users: int):
        """Обновляет метрики пользователей"""
        self.active_users_gauge.set(active_users)
        self.total_users_gauge.set(total_users)
    
    def update_system_metrics(self):
        """Обновляет системные метрики"""
        try:
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()
            
            self.memory_gauge.set(memory_mb)
            self.cpu_gauge.set(cpu_percent)
            
        except Exception as e:
            logger.warning(f"Ошибка обновления системных метрик: {e}")
    
    def get_uptime(self) -> timedelta:
        """Возвращает время работы бота"""
        return timedelta(seconds=time.time() - self.start_time)
    
    def get_system_info(self) -> Dict:
        """Возвращает системную информацию"""
        try:
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()
            
            return {
                'memory_mb': round(memory_mb, 2),
                'cpu_percent': round(cpu_percent, 2),
                'uptime': str(self.get_uptime()),
                'threads': process.num_threads(),
                'open_files': len(process.open_files()),
                'connections': len(process.connections())
            }
        except Exception as e:
            logger.error(f"Ошибка получения системной информации: {e}")
            return {}
    
    def get_bot_stats(self) -> Dict:
        """Возвращает статистику бота"""
        uptime = self.get_uptime()
        
        return {
            'uptime': str(uptime),
            'uptime_seconds': time.time() - self.start_time,
            'commands': self.stats['commands'],
            'requests': self.stats['requests'],
            'total_commands': sum(self.stats['commands'].values()),
            'success_rate': (
                self.stats['requests']['success'] / 
                (self.stats['requests']['success'] + self.stats['requests']['failed'])
                if (self.stats['requests']['success'] + self.stats['requests']['failed']) > 0
                else 0
            )
        }
    
    def format_metrics_report(self) -> str:
        """Форматирует отчет о метриках"""
        system_info = self.get_system_info()
        bot_stats = self.get_bot_stats()
        
        report = "📊 Отчет о метриках бота:\n\n"
        
        # Системная информация
        report += "🖥 Система:\n"
        report += f"⏱ Время работы: {bot_stats['uptime']}\n"
        report += f"💾 Память: {system_info.get('memory_mb', 0)} МБ\n"
        report += f"🖥 CPU: {system_info.get('cpu_percent', 0)}%\n"
        report += f"🧵 Потоки: {system_info.get('threads', 0)}\n\n"
        
        # Статистика команд
        report += "📝 Команды:\n"
        for command, count in sorted(bot_stats['commands'].items(), key=lambda x: x[1], reverse=True):
            report += f"• /{command}: {count}\n"
        
        # Статистика запросов
        requests = bot_stats['requests']
        total_requests = requests['success'] + requests['failed']
        if total_requests > 0:
            success_rate = (requests['success'] / total_requests) * 100
            report += f"\n🌐 Запросы:\n"
            report += f"✅ Успешных: {requests['success']}\n"
            report += f"❌ Ошибок: {requests['failed']}\n"
            report += f"📈 Успешность: {success_rate:.1f}%\n"
        
        return report

class HealthChecker:
    """Проверка здоровья бота"""
    
    def __init__(self, monitoring: MonitoringService):
        self.monitoring = monitoring
        self.last_check = time.time()
        self.health_status = "healthy"
        self.issues = []
    
    def check_health(self) -> Dict:
        """Проверяет здоровье бота"""
        current_time = time.time()
        self.issues = []
        
        # Проверка времени работы
        uptime = current_time - self.monitoring.start_time
        if uptime < 60:  # Меньше минуты
            self.issues.append("Бот только что запущен")
        
        # Проверка памяти
        system_info = self.monitoring.get_system_info()
        memory_mb = system_info.get('memory_mb', 0)
        if memory_mb > 500:  # Больше 500 МБ
            self.issues.append(f"Высокое потребление памяти: {memory_mb:.1f} МБ")
        
        # Проверка CPU
        cpu_percent = system_info.get('cpu_percent', 0)
        if cpu_percent > 80:  # Больше 80%
            self.issues.append(f"Высокая нагрузка CPU: {cpu_percent:.1f}%")
        
        # Проверка успешности запросов
        bot_stats = self.monitoring.get_bot_stats()
        success_rate = bot_stats.get('success_rate', 1.0)
        if success_rate < 0.8:  # Меньше 80%
            self.issues.append(f"Низкая успешность запросов: {success_rate*100:.1f}%")
        
        # Определяем статус
        if not self.issues:
            self.health_status = "healthy"
        elif len(self.issues) <= 2:
            self.health_status = "warning"
        else:
            self.health_status = "critical"
        
        self.last_check = current_time
        
        return {
            'status': self.health_status,
            'issues': self.issues,
            'last_check': datetime.fromtimestamp(current_time).isoformat()
        }
    
    def get_health_emoji(self) -> str:
        """Возвращает эмодзи статуса здоровья"""
        return {
            'healthy': '✅',
            'warning': '⚠️',
            'critical': '❌'
        }.get(self.health_status, '❓')
    
    def format_health_report(self) -> str:
        """Форматирует отчет о здоровье"""
        health = self.check_health()
        
        report = f"{self.get_health_emoji()} Статус здоровья: {health['status'].upper()}\n\n"
        
        if health['issues']:
            report += "🔍 Обнаруженные проблемы:\n"
            for issue in health['issues']:
                report += f"• {issue}\n"
        else:
            report += "🎉 Все системы работают нормально!\n"
        
        report += f"\n⏰ Последняя проверка: {health['last_check']}"
        
        return report 