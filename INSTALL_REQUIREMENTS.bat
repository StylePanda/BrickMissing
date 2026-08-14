@echo off
setlocal
cd /d "%~dp0"
title BrickMissing - Abhaengigkeiten installieren

echo ============================================================
echo  BrickMissing - Python-Abhaengigkeiten installieren
echo ============================================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3.14 --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3.14"
        goto :install
    )

    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
        goto :install
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto :install
)

echo FEHLER: Python wurde nicht gefunden.
echo Bitte Python 3.14 installieren und "Add Python to PATH" aktivieren.
goto :failed

:install
echo Verwendetes Python:
%PYTHON_CMD% --version
echo.

echo pip wird aktualisiert ...
%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo FEHLER: pip konnte nicht aktualisiert werden.
    goto :failed
)

echo.
echo requirements.txt wird installiert ...
%PYTHON_CMD% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo FEHLER: Die Abhaengigkeiten konnten nicht installiert werden.
    goto :failed
)

echo.
echo ============================================================
echo  Installation erfolgreich abgeschlossen.
echo ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo Die Installation wurde nicht erfolgreich abgeschlossen.
echo Bitte die Fehlermeldung oberhalb pruefen.
echo.
pause
exit /b 1
