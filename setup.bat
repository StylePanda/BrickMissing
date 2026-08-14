@echo off
setlocal
cd /d "%~dp0"
title BrickMissing 8.0 - Einrichtung
where py >nul 2>nul
if errorlevel 1 (echo FEHLER: Python Launcher wurde nicht gefunden.& pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto :failed
call ".venv\Scripts\python.exe" -m pip install -r requirements\development.txt
if errorlevel 1 goto :failed
set "DJANGO_SETTINGS_MODULE=config.settings.development"
call ".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 goto :failed
call ".venv\Scripts\python.exe" manage.py collectstatic --noinput
if errorlevel 1 goto :failed
call ".venv\Scripts\python.exe" manage.py check
if errorlevel 1 goto :failed
echo Einrichtung erfolgreich. START_WEBSITE.bat startet Django 8.
pause
exit /b 0
:failed
echo Einrichtung fehlgeschlagen. Vorhandene Daten wurden nicht geloescht.
pause
exit /b 1
