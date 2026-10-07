# Terra Kooplijst

Vervangt de Excel-kooplijst van Terra Inspectioneering. Engineers vragen aan, wie daarvoor is
aangewezen keurt goed, de besteller bestelt per winkel, en de aanvrager vinkt af wat binnen is.

Het is een losse Django-app naast TerraFlow, zelfde opzet als het sales dashboard:

    TerraFlow (poort 8000) --/kooplijst/*--> deze dienst (127.0.0.1:8091), eigen database terra_kooplijst

De app heeft **geen eigen login**. TerraFlow zet hem achter de gewone login en geeft bij elk verzoek
mee wie er kijkt (`X-TerraFlow-User`, `-Name`, `-Admin`) plus een gedeeld geheim (`X-TerraFlow-Secret`).
Zonder dat geheim weigert de dienst alles behalve `/health/`. De TerraFlow-kant staat in
`quotes/kooplijst_views.py` van de TerraFlow-repo.

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

Niet in Terminal. In de scriptmap van TerraFlow (`deploy/macos`):

1. `Update TerraFlow (nieuwe versie ophalen).command` (TerraFlow moet de kooplijst-koppeling kennen)
2. `10 - Kooplijst installeren.command`

Daarna bijwerken met `Update Kooplijst.command`. Beide roepen `deploy/macos/installeer.sh` uit deze repo aan:
venv, database, gedeeld geheim in beide `.env`-bestanden, migraties, twee launchd-diensten
(`nl.terra.kooplijst` en `nl.terra.kooplijst-meldingen`). Opnieuw draaien kan altijd; `.env` en database blijven staan.

Logboek: `/var/log/terraflow/kooplijst.log` en `kooplijst-meldingen.log`. De database zit in de dagelijkse
backup van TerraFlow (`kooplijst.dump`).

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
