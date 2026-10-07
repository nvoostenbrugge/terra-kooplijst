#!/usr/bin/env bash
# Dubbelklik: nieuwste versie van de Kooplijst ophalen, database bijwerken en herstarten.
# Instellingen (.env), database en rechten blijven staan.
APP_DIR="${APP_DIR:-/opt/terraflow}"; DOEL="${KOOP_DIR:-/Users/Shared/terra-kooplijst}"
[ -f "$APP_DIR/deploy/macos/lib.sh" ] || { echo "GESTOPT: TerraFlow is niet gevonden in $APP_DIR."; printf '(Druk op Enter.) '; read -r _; exit 1; }
# shellcheck disable=SC1091
source "$APP_DIR/deploy/macos/lib.sh"
[ -f "$DOEL/deploy/macos/installeer.sh" ] || die "de kooplijst is nog niet geïnstalleerd: 'Kooplijst installeren.command'"
[ -d "$DOEL/.git" ] || die "de kooplijst is geïnstalleerd vanuit een download. Download de nieuwe versie van GitHub en dubbelklik daarin op 'Kooplijst installeren.command'."
need_sudo
sudo chown -R "$(id -un)" "$DOEL" 2>/dev/null   # de map is van de dienstgebruiker; installeer.sh zet dat aan het eind terug
cd "$DOEL" || die "map ontbreekt"
export GIT_TERMINAL_PROMPT=0
say "Code ophalen"; git pull --ff-only || die "git pull mislukt (geen toegang, of lokale wijzigingen in $DOEL)"
git log --oneline -1
chmod +x deploy/macos/*.command deploy/macos/*.sh 2>/dev/null
APP_DIR="$APP_DIR" bash "$DOEL/deploy/macos/installeer.sh" || { sudo chown -R "$APP_USER" "$DOEL" 2>/dev/null; die "bijwerken mislukt (zie de melding hierboven)"; }
hold
