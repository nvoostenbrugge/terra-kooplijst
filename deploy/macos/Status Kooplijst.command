#!/usr/bin/env bash
# Dubbelklik: draait de Kooplijst, en is hij bereikbaar via TerraFlow?
APP_DIR="${APP_DIR:-/opt/terraflow}"; DOEL="${KOOP_DIR:-/Users/Shared/terra-kooplijst}"
[ -f "$APP_DIR/deploy/macos/lib.sh" ] || { echo "GESTOPT: TerraFlow is niet gevonden in $APP_DIR."; printf '(Druk op Enter.) '; read -r _; exit 1; }
# shellcheck disable=SC1091
source "$APP_DIR/deploy/macos/lib.sh"
need_sudo
say "Diensten"; svc_status nl.terra.kooplijst; svc_status nl.terra.kooplijst-meldingen
say "Bereikbaar"
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/health/)
[ "$code" = 200 ] && ok "kooplijst-dienst antwoordt (poort 8091), versie $(cat "$DOEL/VERSION" 2>/dev/null)" || warn "kooplijst-dienst geeft HTTP $code"
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/kooplijst/)
{ [ "$code" = 302 ] || [ "$code" = 200 ]; } && ok "in TerraFlow bereikbaar op /kooplijst/ (achter de login)" || warn "TerraFlow geeft HTTP $code op /kooplijst/"
say "Koppeling in TerraFlow"; "$APP_DIR/venv/bin/python" "$DOEL/deploy/macos/koppel_terraflow.py" status "$APP_DIR" "$DOEL" | sed 's/^/   /'
say "Laatste regels van het logboek"; tail -8 /var/log/terraflow/kooplijst.log 2>/dev/null | sed 's/^/   /'; echo "   ---"; tail -4 /var/log/terraflow/kooplijst-meldingen.log 2>/dev/null | sed 's/^/   /'
hold
