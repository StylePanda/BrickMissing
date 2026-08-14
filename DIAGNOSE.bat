@echo off
setlocal
cd /d "%~dp0"
title BrickMissing 8.0 - Django Diagnose
if not exist ".venv\Scripts\python.exe" (echo FEHLER: .venv fehlt.& exit /b 1)
set "DJANGO_SETTINGS_MODULE=config.settings.development"
call ".venv\Scripts\python.exe" manage.py check
if errorlevel 1 exit /b 1
call ".venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
if errorlevel 1 exit /b 1
call ".venv\Scripts\python.exe" manage.py test
if errorlevel 1 exit /b 1
call ".venv\Scripts\python.exe" -m ruff check .
exit /b %errorlevel%
