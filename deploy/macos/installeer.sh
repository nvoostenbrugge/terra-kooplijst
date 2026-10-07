#!/usr/bin/env bash
# =============================================================================
# Terra Kooplijst installeren of bijwerken op de Mac mini.
#
# Niet zelf starten: de dubbelklik-scripts van TerraFlow doen dat, nadat ze de code hebben opgehaald:
#   "10 - Kooplijst installeren.command"   (eerste keer)
#   "Update Kooplijst.command"             (nieuwe versie)
#
# Idempotent: opnieuw draaien = bijwerken. Instellingen (.env) en database blijven staan.
#
#   TerraFlow (8000) --/kooplijst/*--> deze dienst (8091), eigen database terra_kooplijst
#
# Stappen: Python-omgeving, database, gedeeld geheim (in beide .env-bestanden), migraties,
# twee launchd-diensten (web + meldingen), controle.
# macOS-bash is 3.2: geen ${var^^}, mapfile of declare -A gebruiken.
# =============================================================================
APP_DIR="${APP_DIR:-/opt/terraflow}"
[ -f "$APP_DIR/deploy/macos/lib.sh" ] || { echo "GESTOPT: TerraFlow staat niet in $APP_DIR (lib.sh ontbreekt)"; exit 1; }
# shellcheck disable=SC1091
source "$APP_DIR/deploy/macos/lib.sh"
stop() { printf '\n\033[1;31mGESTOPT: %s\033[0m\n' "$*"; exit 1; }

KOOP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
KOOP_WEB=nl.terra.kooplijst; KOOP_MELD=nl.terra.kooplijst-meldingen; KOOP_PORT=8091; KOOP_DB=terra_kooplijst
cd "$KOOP_DIR" || stop "map $KOOP_DIR ontbreekt"
sudo -v || stop "geen beheerdersrechten"

# 1) Python-omgeving -----------------------------------------------------------
say "Python-omgeving"
PY312="$(command -v python3.12 2>/dev/null)"; [ -x "$PY312" ] || PY312=/opt/homebrew/bin/python3.12
[ -x "$PY312" ] || stop "python3.12 ontbreekt (eerst 'Update TerraFlow' draaien)"
[ -x venv/bin/python ] || "$PY312" -m venv venv || stop "venv aanmaken mislukt"
venv/bin/pip install -q --upgrade pip >/dev/null 2>&1
venv/bin/pip install -q -r requirements.txt || stop "pakketten installeren mislukt (internet?)"
ok "pakketten geïnstalleerd"

# 2) eigen database ------------------------------------------------------------
PSQL=/opt/homebrew/opt/postgresql@16/bin/psql
[ -x "$PSQL" ] || stop "PostgreSQL 16 ontbreekt"
DB_USER_TF="$(env_get DB_USER)"; [ -n "$DB_USER_TF" ] || stop "DB_USER ontbreekt in $APP_DIR/.env"
if "$PSQL" -h localhost -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$KOOP_DB'" 2>/dev/null | grep -q 1; then
  ok "database $KOOP_DB bestaat al"
else
  "$PSQL" -h localhost -d postgres -qc "CREATE DATABASE $KOOP_DB OWNER $DB_USER_TF ENCODING 'UTF8'" || stop "database aanmaken mislukt"
  ok "database $KOOP_DB aangemaakt"
fi

# 3) gedeeld geheim: zelfde waarde in TerraFlow (.env: KOOPLIJST_SECRET) en hier (.env: TERRAFLOW_SECRET) -----
GEHEIM="$(env_get KOOPLIJST_SECRET)"; TF_HERSTART=0
if [ -z "$GEHEIM" ]; then
  GEHEIM="$(venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(40))')"
  env_set KOOPLIJST_SECRET "$GEHEIM"
  TF_HERSTART=1
  ok "gedeeld geheim aangemaakt in $APP_DIR/.env"
fi
DB_HOST_TF="$(env_get DB_HOST)"; DB_PORT_TF="$(env_get DB_PORT)"
if [ ! -f .env ]; then
  cat > .env <<ENV
# Terra Kooplijst - instellingen op de Mac mini (aangemaakt door deploy/macos/installeer.sh)
SECRET_KEY=$(venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(50))')
DEBUG=False
PORT=$KOOP_PORT
DB_NAME=$KOOP_DB
DB_USER=$DB_USER_TF
DB_PASSWORD=$(env_get DB_PASSWORD)
DB_HOST=${DB_HOST_TF:-localhost}
DB_PORT=${DB_PORT_TF:-5432}
TERRAFLOW_SECRET=$GEHEIM
TERRAFLOW_URL=http://127.0.0.1:8000
ENV
  ok ".env aangemaakt (databasegegevens overgenomen van TerraFlow)"
elif grep -q '^TERRAFLOW_SECRET=' .env; then
  sed -i '' "s|^TERRAFLOW_SECRET=.*|TERRAFLOW_SECRET=$GEHEIM|" .env
  ok ".env bestaat al (geheim gelijkgezet met TerraFlow)"
else
  echo "TERRAFLOW_SECRET=$GEHEIM" >> .env
  ok ".env aangevuld met het gedeelde geheim"
fi
chmod 600 .env

# 4) database bijwerken + statische bestanden ------------------------------------
say "Database bijwerken"
venv/bin/python manage.py migrate --noinput 2>&1 | tail -3
[ "${PIPESTATUS[0]}" = 0 ] || stop "migraties mislukt (zie hierboven)"
venv/bin/python manage.py collectstatic --noinput -v 0 || stop "statische bestanden verzamelen mislukt"
ok "versie $(cat VERSION 2>/dev/null) ($(git rev-parse --short HEAD 2>/dev/null))"

# 5) diensten --------------------------------------------------------------------
say "Diensten installeren"
sudo mkdir -p /var/log/terraflow
sudo chown -R "$APP_USER" "$KOOP_DIR" /var/log/terraflow 2>/dev/null
for pl in "$KOOP_WEB" "$KOOP_MELD"; do
  sed -e "s|__KOOP_DIR__|$KOOP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" "deploy/macos/$pl.plist" | sudo tee "/Library/LaunchDaemons/$pl.plist" >/dev/null
  sudo chown root:wheel "/Library/LaunchDaemons/$pl.plist"; sudo chmod 644 "/Library/LaunchDaemons/$pl.plist"
  svc_restart "$pl"
done
wait_http "http://127.0.0.1:$KOOP_PORT/health/" 30 || warn "kooplijst-dienst antwoordt nog niet (zie /var/log/terraflow/kooplijst.log)"

if [ "$TF_HERSTART" = 1 ]; then
  say "TerraFlow herstarten (leest het nieuwe geheim in)"
  svc_restart "$WEB"
  wait_http http://127.0.0.1:8000/accounts/login/ 60 || warn "TerraFlow antwoordt nog niet; wacht een minuut en draai Status.command"
fi

# 6) controle --------------------------------------------------------------------
say "Controle"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$KOOP_PORT/health/")
[ "$code" = 200 ] && ok "kooplijst-dienst antwoordt (poort $KOOP_PORT)" || warn "kooplijst-dienst geeft HTTP $code (zie /var/log/terraflow/kooplijst.log)"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$KOOP_PORT/api/staat/")
[ "$code" = 403 ] && ok "zonder TerraFlow-login geen toegang (HTTP 403)" || warn "onverwacht: /api/staat/ geeft HTTP $code zonder geheim"
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/kooplijst/)
{ [ "$code" = 302 ] || [ "$code" = 200 ]; } && ok "in TerraFlow bereikbaar op /kooplijst/ (achter de login)" \
  || warn "TerraFlow geeft HTTP $code op /kooplijst/ (000 = TerraFlow draait niet; 404 = deze TerraFlow-versie kent de kooplijst nog niet: eerst 'Update TerraFlow')"
exit 0
