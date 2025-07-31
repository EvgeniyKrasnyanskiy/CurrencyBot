@echo off
echo Starting CurrencyBot...
cd /d "%~dp0"
call venv\Scripts\activate
python currency_bot.py
pause 