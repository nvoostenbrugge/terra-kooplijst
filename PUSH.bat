@echo off
setlocal
title Terra Kooplijst - push naar GitHub
cd /d "%~dp0"

REM Zet wijzigingen op https://github.com/nvoostenbrugge/terra-kooplijst (branch main).
REM Daarna op de Mac mini: "Update Kooplijst.command".

git rev-parse --is-inside-work-tree >nul 2>&1 || ( color 0C & echo XX Nog geen git-map: eerst EERSTE-KEER-NAAR-GITHUB.bat & pause & exit /b 1 )

git add -A
git add --chmod=+x -- "deploy/macos/*.command" "deploy/macos/*.sh"
git diff --cached --quiet 2>nul
if not errorlevel 1 goto push

echo Er zijn nog niet-gecommitte wijzigingen:
git --no-pager diff --cached --name-status
echo.
set "MSG="
set /p MSG="Korte omschrijving (Enter = 'Kooplijst update'): "
if "%MSG%"=="" set "MSG=Kooplijst update"
git commit -m "%MSG%"

:push
git push origin main
if errorlevel 1 ( color 0C & echo XX Push mislukt. & pause & exit /b 1 )
color 0A
echo.
echo OK. Op de Mac mini: "Update Kooplijst.command".
pause
