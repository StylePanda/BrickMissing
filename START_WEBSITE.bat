@echo off
setlocal
cd /d "%~dp0"
title BrickMissing 8.0 - Django
if not exist ".venv\Scripts\python.exe" (echo FEHLER: .venv fehlt. Bitte setup.bat ausfuehren.& pause & exit /b 1)
set "DJANGO_SETTINGS_MODULE=config.settings.development"
call ".venv\Scripts\python.exe" manage.py migrate --check
if errorlevel 1 call ".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 goto :failed
call ".venv\Scripts\python.exe" manage.py check
if errorlevel 1 goto :failed
echo BrickMissing 8.0 startet auf http://127.0.0.1:8000
call ".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
exit /b %errorlevel%
:failed
echo Django konnte nicht gestartet werden. Vorhandene Daten wurden nicht geloescht.
pause
exit /b 1
