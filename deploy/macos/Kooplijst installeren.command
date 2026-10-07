#!/usr/bin/env bash
# Dubbelklik: de Kooplijst op deze Mac zetten als eigen dienst naast TerraFlow.
#
#   TerraFlow (8000) --/kooplijst/*--> Django-app (8091), eigen database terra_kooplijst
#
# Werkt vanuit een gedownloade map (GitHub -> Code -> Download ZIP) en vanuit de vaste plek
# /Users/Shared/terra-kooplijst. Vanuit een download wordt de code eerst naar de vaste plek gehaald
# (git clone; lukt dat niet, dan wordt de gedownloade map gekopieerd).
# Idempotent: opnieuw draaien = bijwerken. Het eigenlijke werk staat in installeer.sh.
HIER="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${APP_DIR:-/opt/terraflow}"
DOEL="${KOOP_DIR:-/Users/Shared/terra-kooplijst}"
REPO="${KOOP_REPO:-https://github.com/nvoostenbrugge/terra-kooplijst.git}"
if [ ! -f "$APP_DIR/deploy/macos/lib.sh" ]; then
  echo "GESTOPT: TerraFlow is niet gevonden in $APP_DIR. De kooplijst hoort op de Mac mini waar TerraFlow draait."
  printf '(Druk op Enter.) '; read -r _; exit 1
fi
# shellcheck disable=SC1091
source "$APP_DIR/deploy/macos/lib.sh"
say "Kooplijst installeren op /kooplijst/"
need_sudo

BRON="$(cd "$HIER/../.." && pwd)"
export GIT_TERMINAL_PROMPT=0          # nooit blijven hangen op een inlogvraag van git
[ -d "$DOEL" ] && sudo chown -R "$(id -un)" "$DOEL" 2>/dev/null   # de map is na een eerdere installatie van de dienstgebruiker
if [ "$BRON" = "$DOEL" ]; then
  [ -d "$DOEL/.git" ] && { say "Code bijwerken"; (cd "$DOEL" && git pull -q --ff-only) || warn "git pull mislukt; bestaande code wordt gebruikt"; }
elif [ -d "$DOEL/.git" ]; then
  say "Code bijwerken"; (cd "$DOEL" && git pull -q --ff-only) || warn "git pull mislukt; bestaande code wordt gebruikt"
elif { [ ! -e "$DOEL" ] || [ -z "$(ls -A "$DOEL" 2>/dev/null)" ]; } && git clone -q "$REPO" "$DOEL" 2>/dev/null; then
  ok "code opgehaald van GitHub naar $DOEL"
else
  warn "ophalen van GitHub lukte niet (heeft deze Mac toegang tot de repo?). De gedownloade map wordt gekopieerd; bijwerken kan dan alleen met een nieuwe download."
  # instellingen (.env), Python-omgeving en backups van een eerdere installatie blijven staan
  mkdir -p "$DOEL" && (cd "$BRON" && tar --exclude ./venv --exclude ./.env --exclude ./staticfiles --exclude ./.koppeling-backup --exclude ./.git -cf - .) | (cd "$DOEL" && tar -xf -) \
    && [ -f "$DOEL/deploy/macos/installeer.sh" ] || die "kopiëren naar $DOEL mislukt"
  ok "code gekopieerd naar $DOEL"
fi
[ -f "$DOEL/deploy/macos/installeer.sh" ] || die "installeer.sh ontbreekt in $DOEL"
chmod +x "$DOEL"/deploy/macos/*.command "$DOEL"/deploy/macos/*.sh 2>/dev/null
xattr -dr com.apple.quarantine "$DOEL" 2>/dev/null

APP_DIR="$APP_DIR" bash "$DOEL/deploy/macos/installeer.sh" || { [ -f "/Library/LaunchDaemons/nl.terra.kooplijst.plist" ] && sudo chown -R "$APP_USER" "$DOEL" 2>/dev/null; die "installatie mislukt (zie de melding hierboven)"; }

hold
