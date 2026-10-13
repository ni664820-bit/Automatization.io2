@echo off
rem ============================================================
rem  booking-bot: запуск с автоперезапуском при падении
rem  Добавить в автозагрузку:
rem    schtasks /create /tn "booking-bot" /tr "\"C:\Path\to\start.bat\"" /sc onlogon
rem ============================================================
cd /d %~dp0

if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

:loop
echo [%date% %time%] Запуск бота...
%PY% app.py
echo [%date% %time%] Бот остановился с кодом %ERRORLEVEL%, перезапуск через 10 сек...
timeout /t 10 /nobreak >nul
goto loop
