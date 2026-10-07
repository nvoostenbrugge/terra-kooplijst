# Terra Kooplijst

Vervangt de Excel-kooplijst van Terra Inspectioneering. Engineers vragen aan, wie daarvoor is
aangewezen keurt goed, de besteller bestelt per winkel, en de aanvrager vinkt af wat binnen is.

Het is een losse Django-app naast TerraFlow, zelfde opzet als het sales dashboard:

    TerraFlow (poort 8000) --/kooplijst/*--> deze dienst (127.0.0.1:8091), eigen database terra_kooplijst

De app heeft **geen eigen login**. TerraFlow zet hem achter de gewone login en geeft bij elk verzoek
mee wie er kijkt (`X-TerraFlow-User`, `-Name`, `-Admin`) plus een gedeeld geheim (`X-TerraFlow-Secret`).
Zonder dat geheim weigert de dienst alles behalve `/health/`. De TerraFlow-kant staat in deze repo in
`terraflow/` en wordt door de installatie in TerraFlow gezet (zie hieronder); wijzigingen daaraan dus hier doen.

## Wie ziet en mag wat

| Wie | Ziet | Mag |
|---|---|---|
| Iedereen | alleen eigen aanvragen | aanvragen, eigen aanvraag wijzigen zolang hij op akkoord wacht, eigen artikelen afvinken |
| Mag goedkeuren | de hele lijst | akkoord geven, afwijzen |
| Mag bestellen | de hele lijst | op besteld zetten, volglink toevoegen, bestelmomenten instellen |
| Super-admin in TerraFlow | de hele lijst | alles, plus Beheer: rechten uitdelen, oude Excel-lijst inladen |

Rechten worden op de server afgedwongen (`inkoop/views.py`), niet alleen in de pagina verborgen.

## Meldingen

Pushmeldingen lopen via TerraFlow (`POST /api/internal/kooplijst/push/`), zodat apparaten en sleutels daar blijven.

- Direct: spoedaanvraag naar wie mag goedkeuren; goedgekeurde spoed naar wie mag bestellen;
  "besteld" en "onderweg" naar de aanvrager.
- Elk kwartier op werkdagen tussen 8 en 18 uur (`manage.py kooplijst_meldingen`): nieuwe gewone aanvragen
  gebundeld, aanvragen die langer dan 2 werkdagen op akkoord wachten (hooguit 1x per dag), en goedgekeurde
  artikelen die een bestelronde gemist hebben (1x per ronde).

In de testmodus van TerraFlow gaan er alleen pushmeldingen uit als `push` in `TERRAFLOW_SAFE_MODE_ALLOW` staat.

## Volglinks

Een volglink wordt alleen geaccepteerd van een bekende vervoerder (lijst in `kooplijst_site/settings.py`,
`VERVOERDER_DOMEINEN`) en alleen via https. Links naar een winkelaccount of uit een bestelmail worden geweigerd,
zodat er nooit een inloglink bij een engineer terechtkomt.

## Installeren en bijwerken op de Mac mini

Niet in Terminal, en zonder de TerraFlow-repo vanaf de laptop te pushen.

**Gewone weg: via TerraFlow zelf**

1. Plak de tekst van `terraflow/OPDRACHT-VOOR-TERRAFLOW.md` als opdracht in TerraFlow (adminpaneel, kaart Ontwikkeling).
   Claude op de testserver zet dan de koppeling in TerraFlow (met `deploy/macos/koppel_terraflow.py` uit deze repo)
   en maakt het script `10 - Kooplijst installeren.command` in de scriptmap van TerraFlow.
2. Beoordelen, goedkeuren en uitrollen zoals elke opdracht.
3. Op de productie-Mac: dubbelklik `10 - Kooplijst installeren.command`. Die haalt deze repo naar
   `/Users/Shared/terra-kooplijst` en draait `Kooplijst installeren.command` hieruit. De koppeling staat er dan al,
   dus het script installeert alleen de dienst.

**Reserve: rechtstreeks op de Mac** (als de weg via TerraFlow niet kan; het script zet de koppeling er dan zelf bij)

1. Op de Mac mini in de browser: deze repo openen, groene knop **Code**, **Download ZIP**. Dubbelklik de zip in Downloads.
2. In de uitgepakte map: `deploy/macos`, rechtsklik op **Kooplijst installeren.command**, **Open**
   (macOS vraagt bij een gedownload script eenmalig om bevestiging; op macOS 15 en nieuwer staat die bevestiging onder
   Systeeminstellingen, Privacy en beveiliging, "Open toch").
3. Het script vraagt het wachtwoord van de Mac en later één keer of de koppeling in TerraFlow mag komen (Enter = ja).

Wat het script doet:

- code naar de vaste plek `/Users/Shared/terra-kooplijst` (git clone; lukt dat niet, dan wordt de download gekopieerd);
- Python-omgeving, eigen database `terra_kooplijst`, gedeeld geheim in beide `.env`-bestanden, migraties;
- **koppeling in TerraFlow** (`/opt/terraflow`), met `deploy/macos/koppel_terraflow.py`:
  `quotes/kooplijst_views.py` en `quotes/test_kooplijst.py` (kopie uit `terraflow/` van deze repo), drie routes in
  `quotes/urls.py`, twee instellingen in `terra_quotes/settings.py`, de knop in `quotes/services/project_helpers.py`
  en de kooplijst-database in `deploy/macos/backup.sh`. Er wordt alleen toegevoegd, op een herkenbare plek. Is zo'n
  plek er niet, dan stopt het script zonder iets te wijzigen;
- controle: `manage.py check` en de zeven tests van de koppeling. Slaagt een van beide niet, dan gaat alles terug
  naar hoe het was (kopie in `.koppeling-backup/`) en blijft TerraFlow ongewijzigd;
- de wijziging wordt op de Mac in de git-geschiedenis van TerraFlow vastgelegd (één commit). TerraFlow toont daarna
  "1 niet op GitHub"; **Push naar GitHub.command** op de Mac stuurt hem naar de Mac-repo;
- twee launchd-diensten (`nl.terra.kooplijst` en `nl.terra.kooplijst-meldingen`) en een herstart van TerraFlow
  (de site is een paar tellen weg; kies een rustig moment).

**Daarna**, in `/Users/Shared/terra-kooplijst/deploy/macos`:

- `Update Kooplijst.command`: nieuwe versie ophalen en herstarten. Na een installatie vanuit een download
  (geen git clone) is bijwerken: opnieuw de ZIP downloaden en daarin weer `Kooplijst installeren.command`.
- `Status Kooplijst.command`: draait hij, is hij bereikbaar, staat de koppeling er.

Opnieuw draaien kan altijd; `.env`, database en rechten blijven staan.

Logboek: `/var/log/terraflow/kooplijst.log` en `kooplijst-meldingen.log`. De database gaat mee in de nachtelijke
backup van TerraFlow (`config/kooplijst/kooplijst.dump`, plus de `.env`). Terugzetten gaat niet vanzelf met
"Herstel vanaf backup": dat is `pg_restore` van die dump in de database `terra_kooplijst`.

Koppeling weer uit TerraFlow halen: `python3 deploy/macos/koppel_terraflow.py terug /opt/terraflow <map in .koppeling-backup>`
(of de commit in `/opt/terraflow` terugdraaien) en TerraFlow herstarten.

## Van de laptop naar GitHub

`EERSTE-KEER-NAAR-GITHUB.bat` (eenmalig) en daarna `PUSH.bat`. Die pushen alleen deze map.

## Eerste keer gebruiken

Open de Kooplijst als super-admin en klik op **Beheer**:

1. Vink aan wie mag goedkeuren en wie mag bestellen.
2. Laad het Excel-bestand van de oude kooplijst in (eerst Proefdraai). Alleen wat nog openstaat komt mee:
   "OK" wordt akkoord, een lege eerste kolom wacht op akkoord, en bestellingen van de laatste 14 dagen
   zonder ontvangstdatum komen onder Onderweg.
3. Koppel de namen uit de oude lijst aan collega's zodra die de kooplijst een keer geopend hebben.

## Lokaal proberen (Windows-laptop)

Dubbelklik `START-LOKAAL.bat`. Die maakt een venv, gebruikt SQLite en opent de app op http://127.0.0.1:8091/
met een nep-gebruiker (super-admin). Dat werkt alleen met `DEBUG=True`; op de Mac staat DEBUG uit.

Tests: `venv\Scripts\python manage.py test` (Mac: `venv/bin/python manage.py test`).

## Nog niet gebouwd

- Volglinks automatisch uit de info@-mailbox halen. Nu plakt de besteller de link van de vervoerder.
- De Claude-taak op de pc van de besteller die de winkelwagens vult. De app heeft er al de ingangen voor
  (`GET /api/vultaak/`, `POST /api/wagens/`) en toont het resultaat per winkel; het vulmoment stel je in
  onder Bestelmomenten.
