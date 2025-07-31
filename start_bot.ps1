Write-Host "Starting CurrencyBot..." -ForegroundColor Green
Set-Location $PSScriptRoot
& ".\venv\Scripts\Activate.ps1"
python currency_bot.py 