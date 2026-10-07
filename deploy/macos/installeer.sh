#!/usr/bin/env bash
# =============================================================================
# Terra Kooplijst installeren of bijwerken op de Mac mini.
#
# Niet zelf starten: de dubbelklik-scripts in deze map doen dat, nadat ze de code hebben opgehaald:
#   "Kooplijst installeren.command"   (eerste keer)
#   "Update Kooplijst.command"        (nieuwe versie)
#
# Idempotent: opnieuw draaien = bijwerken. Instellingen (.env) en database blijven staan.
#
#   TerraFlow (8000) --/kooplijst/*--> deze dienst (8091), eigen database terra_kooplijst
#
# Stappen: Python-omgeving, database, gedeeld geheim (in beide .env-bestanden), migraties,
# koppeling in TerraFlow (routes + knop, met backup, controle en terugdraaien), twee launchd-diensten
# (web + meldingen), controle. De TerraFlow-repo op de laptop hoeft hiervoor niet gepusht te worden.
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
IK="$(id -un)"
# TerraFlow is van de dienstgebruiker ($APP_USER); alles in $APP_DIR (git, manage.py) draait als die gebruiker.
als_app() { if [ "$IK" = "$APP_USER" ]; then "$@"; else sudo -u "$APP_USER" -H "$@"; fi; }
# Tijdens het installeren is de kooplijst-map van wie dit script draait; aan het eind (stap 6) weer van de dienstgebruiker.
sudo chown -R "$IK" "$KOOP_DIR" 2>/dev/null

# 1) Python-omgeving -----------------------------------------------------------
say "Python-omgeving"
PY312="$(command -v python3.12 2>/dev/null)"; [ -x "$PY312" ] || PY312=/opt/homebrew/bin/python3.12
[ -x "$PY312" ] || PY312="$APP_DIR/venv/bin/python"       # anders dezelfde Python als TerraFlow (zelfde Django-versie)
[ -x "$PY312" ] || stop "geen Python gevonden (python3.12 of $APP_DIR/venv/bin/python)"
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

# 5) koppeling in TerraFlow ------------------------------------------------------
# TerraFlow moet /kooplijst/ doorgeven en pushmeldingen aannemen. Dat zijn een paar regels in de
# TerraFlow-code op deze Mac; koppel_terraflow.py zet ze erbij (alleen toevoegen, met backup).
say "Koppeling met TerraFlow"
TFPY="$APP_DIR/venv/bin/python"; KOPPEL="$KOOP_DIR/deploy/macos/koppel_terraflow.py"
KOPPEL_BESTANDEN="quotes/urls.py terra_quotes/settings.py quotes/services/project_helpers.py deploy/macos/backup.sh quotes/kooplijst_views.py quotes/test_kooplijst.py"
[ -x "$TFPY" ] || stop "Python van TerraFlow ontbreekt ($TFPY)"
KOPPELING=0
UIT="$(als_app "$TFPY" "$KOPPEL" status "$APP_DIR" "$KOOP_DIR" 2>&1)"; RC=$?
if [ "$RC" != 0 ]; then
  echo "$UIT" | sed 's/^/   /'
  stop "De TerraFlow op deze Mac heeft een andere opzet dan verwacht. Er is niets aan TerraFlow gewijzigd. Stuur deze melding door."
elif echo "$UIT" | grep -q '^COMPLEET'; then
  KOPPELING=1; ok "koppeling staat al in TerraFlow"
else
  echo "   Dit komt erbij in $APP_DIR (er wordt alleen toegevoegd; van elk bestand gaat eerst een kopie apart):"
  echo "$UIT" | sed -n 's/^ONTBREEKT /     + /p'
  echo "$UIT" | sed -n 's/^OVERGESLAGEN /     (overgeslagen) /p'
  printf '   Toevoegen aan TerraFlow? [J/n] '; read -r ANTW
  case "$ANTW" in
    n|N|nee|Nee|NEE)
      warn "koppeling NIET toegevoegd: de kooplijst-dienst draait straks wel, maar is niet bereikbaar via TerraFlow" ;;
    *)
      VUIL=""; [ -d "$APP_DIR/.git" ] && VUIL="$(cd "$APP_DIR" && als_app git status --porcelain -- $KOPPEL_BESTANDEN 2>/dev/null)"
      # Als beheerder (sudo): schrijven mag dan altijd, bestaande bestanden houden hun eigenaar, nieuwe krijgen die van hun map.
      UIT="$(sudo "$TFPY" "$KOPPEL" toepas "$APP_DIR" "$KOOP_DIR" 2>&1)"; RC=$?
      [ "$RC" = 0 ] || { echo "$UIT" | sed 's/^/   /'; stop "koppeling aanbrengen mislukt; TerraFlow is ongewijzigd"; }
      BACKUP="$(echo "$UIT" | sed -n 's/^BACKUP //p')"
      GEWIJZIGD="$(echo "$UIT" | sed -n 's/^GEWIJZIGD //p' | tr '\n' ' ')"
      terugdraaien() { sudo "$TFPY" "$KOPPEL" terug "$APP_DIR" "$BACKUP" >/dev/null 2>&1; }
      ok "toegevoegd (kopie van de oude bestanden: $BACKUP)"
      LOGC="$(mktemp /tmp/kooplijst-check.XXXXXX)"; LOGT="$(mktemp /tmp/kooplijst-test.XXXXXX)"
      # Controle 1: start TerraFlow nog?
      if ! (cd "$APP_DIR" && als_app "$TFPY" manage.py check > "$LOGC" 2>&1); then
        terugdraaien; tail -15 "$LOGC" | sed 's/^/   /'
        stop "TerraFlow start niet met de koppeling. Alles is teruggezet zoals het was. Stuur deze melding door."
      fi
      ok "TerraFlow start met de koppeling"
      # Controle 2: de tests van de koppeling (eigen testdatabase, raakt de echte data niet)
      # Django maakt daarvoor een database test_<naam> aan en ruimt die weer op. Bestaat er al een met die naam, dan
      # blijven we eraf (die zou anders gewist worden) en slaan we de tests over.
      TESTDB="test_$(env_get DB_NAME)"; : > "$LOGT"; TRC=0
      if "$PSQL" -h localhost -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$TESTDB'" 2>/dev/null | grep -q 1; then
        echo "overgeslagen: database $TESTDB bestaat al" > "$LOGT"
      else
        echo "   Tests van de koppeling draaien (1-3 minuten)..."
        (cd "$APP_DIR" && als_app "$TFPY" manage.py test quotes.test_kooplijst --noinput > "$LOGT" 2>&1); TRC=$?
      fi
      if grep -q '^Ran [0-9]* test' "$LOGT"; then
        if [ "$TRC" = 0 ]; then
          ok "$(grep '^Ran [0-9]* test' "$LOGT" | head -1): geslaagd"
        else
          terugdraaien; tail -25 "$LOGT" | sed 's/^/   /'
          stop "De tests van de koppeling slagen niet op deze TerraFlow. Alles is teruggezet zoals het was. Stuur deze melding door."
        fi
      else
        warn "de tests zijn niet gedraaid ($(head -1 "$LOGT" | cut -c1-80)); de koppeling blijft staan omdat de startcontrole slaagde"
      fi
      # Vastleggen in de git-geschiedenis van TerraFlow op deze Mac (anders struikelt een latere update erover)
      if [ -d "$APP_DIR/.git" ]; then
        if [ -n "$VUIL" ]; then
          warn "niet vastgelegd in git: deze bestanden hadden al eigen, niet-vastgelegde wijzigingen. Leg ze zelf vast."
        else
          ( cd "$APP_DIR"
            als_app git config user.name  >/dev/null || als_app git config user.name  "Niek van Oostenbrugge (Mac mini)"
            als_app git config user.email >/dev/null || als_app git config user.email "nvoostenbrugge@terra-inspectioneering.com"
            als_app git add -- $GEWIJZIGD && als_app git commit -q -m "Kooplijst-koppeling: /kooplijst/ achter de login, push-ingang, knop en backup

Aangebracht door de installatie van terra-kooplijst (deploy/macos/koppel_terraflow.py).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Epag3mhASxAnvP83WKpmgP" -- $GEWIJZIGD ) \
            && ok "vastgelegd in git ($(cd "$APP_DIR" && als_app git rev-parse --short HEAD)); naar GitHub sturen kan met 'Push naar GitHub.command'" \
            || warn "vastleggen in git lukte niet; de wijzigingen staan er wel"
        fi
      fi
      KOPPELING=1; TF_HERSTART=1 ;;
  esac
fi

# 6) diensten --------------------------------------------------------------------
say "Diensten installeren"
sudo mkdir -p /var/log/terraflow
sudo chown -R "$APP_USER" "$KOOP_DIR" /var/log/terraflow 2>/dev/null
for pl in "$KOOP_WEB" "$KOOP_MELD"; do
  sed -e "s|__KOOP_DIR__|$KOOP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" "deploy/macos/$pl.plist" | sudo tee "/Library/LaunchDaemons/$pl.plist" >/dev/null
  sudo chown root:wheel "/Library/LaunchDaemons/$pl.plist"; sudo chmod 644 "/Library/LaunchDaemons/$pl.plist"
  svc_restart "$pl"
done
wait_http "http://127.0.0.1:$KOOP_PORT/health/" 30 || warn "kooplijst-dienst antwoordt nog niet (zie /var/log/terraflow/kooplijst.log)"

# Koppeling staat er, maar de draaiende TerraFlow kent hem nog niet (bv. na een eerder afgebroken installatie): ook herstarten.
if [ "$KOPPELING" = 1 ] && [ "$TF_HERSTART" = 0 ] && [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/kooplijst/)" = 404 ]; then TF_HERSTART=1; fi
if [ "$TF_HERSTART" = 1 ]; then
  say "TerraFlow herstarten (leest de koppeling en het geheim in; de site is een paar tellen weg)"
  svc_restart "$WEB"
  wait_http http://127.0.0.1:8000/accounts/login/ 60 || warn "TerraFlow antwoordt nog niet; wacht een minuut en draai Status.command"
fi

# 7) controle --------------------------------------------------------------------
say "Controle"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$KOOP_PORT/health/")
[ "$code" = 200 ] && ok "kooplijst-dienst antwoordt (poort $KOOP_PORT)" || warn "kooplijst-dienst geeft HTTP $code (zie /var/log/terraflow/kooplijst.log)"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$KOOP_PORT/api/staat/")
[ "$code" = 403 ] && ok "zonder TerraFlow-login geen toegang (HTTP 403)" || warn "onverwacht: /api/staat/ geeft HTTP $code zonder geheim"
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/kooplijst/)
if [ "$code" = 302 ] || [ "$code" = 200 ]; then
  ok "in TerraFlow bereikbaar op /kooplijst/ (achter de login)"
  echo
  echo "  In TerraFlow: knop 'Kooplijst' bovenin bij de borden, of https://<adres>/kooplijst/ (gewone TerraFlow-login)."
  echo "  Eerste keer, als super-admin: knop Beheer -> kies wie mag goedkeuren en bestellen, en laad de oude Excel-kooplijst in."
  echo "  Pushmeldingen werken in testmodus pas met 'push' in de uitzonderingen (3b - Testmodus uitzonderingen.command)."
elif [ "$KOPPELING" = 0 ]; then
  warn "de kooplijst draait, maar is nog niet bereikbaar via TerraFlow: de koppeling ontbreekt. Draai dit script opnieuw en antwoord J."
else
  warn "TerraFlow geeft HTTP $code op /kooplijst/ (000 = TerraFlow draait niet -> 'Herstart TerraFlow.command')"
fi
echo "  Voortaan: $KOOP_DIR/deploy/macos/ -> 'Update Kooplijst.command' en 'Status Kooplijst.command'."
exit 0
