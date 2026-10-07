@echo off
setlocal
title Terra Kooplijst - lokaal proberen
cd /d "%~dp0"

REM Lokaal proberen op de laptop: SQLite, geen TerraFlow nodig, nep-gebruiker (super-admin).
REM Werkt alleen met DEBUG=True; op de Mac mini staat DEBUG uit en komt de gebruiker van TerraFlow.

if not exist venv\Scripts\python.exe (
    echo Python-omgeving aanmaken...
    py -3 -m venv venv 2>nul || python -m venv venv
    if not exist venv\Scripts\python.exe ( color 0C & echo XX Python niet gevonden. & pause & exit /b 1 )
)
venv\Scripts\python -m pip install -q --upgrade pip
venv\Scripts\python -m pip install -q -r requirements.txt
if errorlevel 1 ( color 0C & echo XX Pakketten installeren mislukt. & pause & exit /b 1 )

set DEBUG=True
set DEV_USER=nvoostenbrugge@terra-inspectioneering.com
set DEV_ADMIN=1
set DB_USER=
venv\Scripts\python manage.py migrate --noinput
if errorlevel 1 ( color 0C & echo XX Database bijwerken mislukt. & pause & exit /b 1 )

echo.
echo Kooplijst draait op http://127.0.0.1:8091/  (stoppen: Ctrl+C)
start "" http://127.0.0.1:8091/
venv\Scripts\python manage.py runserver 127.0.0.1:8091
pause
