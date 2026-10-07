Kooplijst koppelen aan TerraFlow (losse dienst, zelfde opzet als het sales dashboard)

Achtergrond
De Kooplijst vervangt de Excel-kooplijst. Het is een losse Django-dienst in een eigen repo:
https://github.com/nvoostenbrugge/terra-kooplijst (openbaar, branch main). Hij draait straks op de Mac op
127.0.0.1:8091 met een eigen database (terra_kooplijst) en heeft geen eigen login. TerraFlow moet hem, net als
het sales dashboard, achter de gewone login tonen op /kooplijst/ en bij elk verzoek meegeven wie er kijkt.
Andersom vraagt de dienst via TerraFlow om pushmeldingen. Alle code voor de TerraFlow-kant is al geschreven
en getest en staat in die repo. Jouw werk is die code hier op zijn plek zetten, niets nieuws verzinnen.

Wat je doet
1. Haal de repo op in een tijdelijke map buiten deze projectmap:
   git clone --depth 1 https://github.com/nvoostenbrugge/terra-kooplijst.git /tmp/terra-kooplijst
   Lukt dat niet, stop dan (spelregel 9) en meld dat de repo niet bereikbaar is.

2. Laat het meegeleverde script de koppeling aanbrengen, vanuit de projectmap:
   venv/bin/python /tmp/terra-kooplijst/deploy/macos/koppel_terraflow.py status . /tmp/terra-kooplijst
   venv/bin/python /tmp/terra-kooplijst/deploy/macos/koppel_terraflow.py toepas . /tmp/terra-kooplijst
   Het script voegt alleen toe en raakt bestaande regels niet aan:
   - quotes/kooplijst_views.py en quotes/test_kooplijst.py (kopie uit de map terraflow/ van de repo)
   - quotes/urls.py: routes kooplijst/, kooplijst/<path:path> en api/internal/kooplijst/push/
   - terra_quotes/settings.py: KOOPLIJST_UPSTREAM en KOOPLIJST_SECRET (uit .env, standaard leeg)
   - quotes/services/project_helpers.py: knop "Kooplijst" in get_user_allowed_views, alleen als KOOPLIJST_SECRET gezet is
   - deploy/macos/backup.sh: database terra_kooplijst mee in de nachtelijke backup (config/kooplijst/)
   Meldt het script FOUT of OVERGESLAGEN voor een bestand, breng dan precies die ene toevoeging met de hand aan;
   de tekst staat bovenin koppel_terraflow.py (URLS_ROUTES, SETTINGS_BLOK, KNOP_BLOK, BACKUP_BLOK).
   Bekijk daarna de diff: er horen alleen toevoegingen in te staan.

3. Maak deploy/macos/10 - Kooplijst installeren.command (uitvoerbaar, mode 755), met deze inhoud:

   #!/usr/bin/env bash
   # Dubbelklik: de Kooplijst (github.com/nvoostenbrugge/terra-kooplijst) op deze Mac zetten of bijwerken.
   # Eigen dienst op poort 8091 met eigen database; TerraFlow toont hem achter de login op /kooplijst/
   # (quotes/kooplijst_views.py). Het eigenlijke werk staat in de kooplijst-repo zelf.
   cd "$(dirname "$0")" && source ./lib.sh
   KOOP_DIR="${KOOP_DIR:-/Users/Shared/terra-kooplijst}"
   if [ ! -f "$KOOP_DIR/deploy/macos/Kooplijst installeren.command" ]; then
     say "Kooplijst ophalen"
     git clone -q https://github.com/nvoostenbrugge/terra-kooplijst.git "$KOOP_DIR" || die "clone mislukt"
   fi
   exec bash "$KOOP_DIR/deploy/macos/Kooplijst installeren.command"

   Neem de kooplijst daarnaast op waar het sales dashboard ook genoemd wordt in de scripts: een regel in
   "LEES-MIJ - welk script wanneer.txt", het menu van "00 - START HIER.command", en in Status.command een blokje
   "Kooplijst" via een functie kooplijst_status in lib.sh naar het voorbeeld van sales_status (dienst
   nl.terra.kooplijst, http://127.0.0.1:8091/health/ moet 200 geven, http://127.0.0.1:8000/kooplijst/ moet 302
   of 200 geven; is /Library/LaunchDaemons/nl.terra.kooplijst.plist er niet, dan alleen "niet geïnstalleerd").

4. Controle
   - venv/bin/python manage.py check
   - venv/bin/python manage.py test (alles groen; quotes.test_kooplijst bevat 7 tests voor deze koppeling)
   - Verwacht gedrag op de testserver, waar de dienst zelf niet draait en KOOPLIJST_SECRET leeg is: geen knop
     "Kooplijst", en /kooplijst/ toont na inloggen de nette melding "Kooplijst is nog niet geïnstalleerd" (404).
     Dat is goed zo; de dienst hoeft op de testserver niet geïnstalleerd te worden.

Niet doen
- Geen modellen, geen migraties, geen nieuwe pakketten (requests zit er al in voor het sales dashboard).
- kooplijst_views.py en test_kooplijst.py niet aanpassen: de bron is de kooplijst-repo. Past iets niet op deze
  TerraFlow, verander dan niets en meld wat er schuurt.
- Geen geheim in code of in git: KOOPLIJST_SECRET komt alleen in .env en wordt op productie door de installatie gezet.
- De CSRF-controle op /kooplijst/ laten staan; alleen de push-ingang is csrf_exempt en die vraagt het gedeelde geheim.
- De kooplijst-code zelf (map inkoop/ van de repo) hoort niet in TerraFlow.

Na het uitrollen (voor Niek, niet voor jou): op de productie-Mac dubbelklik
"10 - Kooplijst installeren.command". Die zet de dienst, de database en het gedeelde geheim neer en herstart TerraFlow.

Sluit je antwoord af met: CONTROLE: /kooplijst/
