@echo off
setlocal
title Terra Kooplijst - eerste keer naar GitHub
cd /d "%~dp0"

REM ==============================================================================
REM  EERSTE-KEER-NAAR-GITHUB.bat
REM  Zet deze map als nieuwe repo op https://github.com/nvoostenbrugge/terra-kooplijst
REM
REM  Vooraf, eenmalig op github.com: New repository, naam "terra-kooplijst", Private,
REM  ZONDER readme/.gitignore/licentie (de repo moet leeg zijn).
REM  Daarna voortaan: PUSH.bat
REM
REM  Dit pusht ALLEEN deze map. De TerraFlow-repo (TerraQuoteSystem-develop) blijft erbuiten:
REM  wat TerraFlow nodig heeft zet de installatie op de Mac er daar zelf bij.
REM ==============================================================================

set "REPO_URL=https://github.com/nvoostenbrugge/terra-kooplijst.git"

git --version >nul 2>&1 || ( color 0C & echo XX Git is niet geinstalleerd. & pause & exit /b 1 )

if not exist .git (
    git init -b main
    if errorlevel 1 ( color 0C & echo XX git init mislukt. & pause & exit /b 1 )
)
git remote get-url origin >nul 2>&1 || git remote add origin %REPO_URL%
git remote set-url origin %REPO_URL%

git add -A
REM De dubbelklik-scripts moeten op de Mac uitvoerbaar zijn; Windows kent dat vinkje niet, dus hier vastleggen.
git add --chmod=+x -- "deploy/macos/*.command" "deploy/macos/*.sh"
git diff --cached --quiet 2>nul
if errorlevel 1 git commit -m "Terra Kooplijst: eerste versie"

echo.
echo Doel: %REPO_URL%  (branch main)
git push -u origin main
if errorlevel 1 (
    color 0C
    echo.
    echo XX Push mislukt. Bestaat de lege repo "terra-kooplijst" op github.com/nvoostenbrugge?
    pause & exit /b 1
)
color 0A
echo.
echo OK, de kooplijst staat op GitHub. Alleen deze map is gepusht; TerraFlow is niet aangeraakt.
echo.
echo Op de Mac mini:
echo   1. Open in de browser  https://github.com/nvoostenbrugge/terra-kooplijst
echo      groene knop Code, dan Download ZIP. Dubbelklik de zip in Downloads.
echo   2. In de uitgepakte map: deploy, macos, rechtsklik op
echo      "Kooplijst installeren.command" en kies Open.
echo   Meer staat in README.md.
pause
