#!/usr/bin/env python3
"""
Zet de kooplijst-koppeling in een bestaande TerraFlow-map (op de Mac: /opt/terraflow).

    koppel_terraflow.py status  <terraflow-map> <kooplijst-map>   -> wat ontbreekt er nog?
    koppel_terraflow.py toepas  <terraflow-map> <kooplijst-map>   -> aanbrengen (met backup)
    koppel_terraflow.py terug   <terraflow-map> <backup-map>      -> een toepassing ongedaan maken

Wat er in TerraFlow bij komt:
  quotes/kooplijst_views.py, quotes/test_kooplijst.py   (kopie uit terraflow/ van de kooplijst-repo)
  quotes/urls.py                      drie routes: /kooplijst/, /kooplijst/<pad> en de push-ingang
  terra_quotes/settings.py            KOOPLIJST_UPSTREAM en KOOPLIJST_SECRET (uit .env)
  quotes/services/project_helpers.py  knop "Kooplijst" in de bord-wisselaar          (mag ontbreken)
  deploy/macos/backup.sh              database van de kooplijst mee in de backup     (mag ontbreken)

Veilig bedoeld voor een TerraFlow die intussen is doorontwikkeld:
  - er wordt alleen iets TOEGEVOEGD op een herkenbare plek; bestaande regels blijven staan;
  - eerst wordt alles gecontroleerd, daarna pas geschreven: ontbreekt een verplichte plek, dan gebeurt er niets;
  - van elk bestand dat verandert gaat eerst een kopie naar <kooplijst-map>/.koppeling-backup/<tijdstip>/;
  - twee keer draaien verandert niets (alles wat er al staat wordt overgeslagen).

Uitvoer: leesbare regels, plus regels "GEWIJZIGD <pad>" en "BACKUP <map>" voor het installatiescript.
Afsluitcode: 0 = gelukt (of niets te doen), 2 = verplichte plek niet gevonden (niets gewijzigd),
3 = geen schrijfrechten in de TerraFlow-map (niets gewijzigd), 1 = andere fout (alles teruggezet).
Alleen de standaardbibliotheek; draait met elke Python 3.8+.
"""
import os
import shutil
import sys
import time
from pathlib import Path

URLS_IMPORT = "from . import kooplijst_views  # Kooplijst (losse dienst): zie quotes/kooplijst_views.py\n"
URLS_ROUTES = (
    "    # ─── Kooplijst (losse dienst, poort 8091) achter de TerraFlow-login + push-ingang voor die dienst ───\n"
    "    path('kooplijst/', kooplijst_views.kooplijst_proxy, name='kooplijst'),\n"
    "    path('kooplijst/<path:path>', kooplijst_views.kooplijst_proxy, name='kooplijst_path'),\n"
    "    path('api/internal/kooplijst/push/', kooplijst_views.kooplijst_push, name='kooplijst_push'),\n"
)
SETTINGS_BLOK = (
    "\n"
    "# Kooplijst (losse dienst, github.com/nvoostenbrugge/terra-kooplijst): zie quotes/kooplijst_views.py.\n"
    "# KOOPLIJST_SECRET wordt gezet door de installatie van de kooplijst; leeg = niet geïnstalleerd.\n"
    "KOOPLIJST_UPSTREAM = config('KOOPLIJST_UPSTREAM', default='http://127.0.0.1:8091')\n"
    "KOOPLIJST_SECRET = config('KOOPLIJST_SECRET', default='')\n"
)
KNOP_BLOK = (
    "    # 🛒 Kooplijst: losse dienst achter /kooplijst/ (quotes/kooplijst_views.py). Knop voor iedereen met\n"
    "    # een rol, maar pas zodra de dienst geïnstalleerd is (KOOPLIJST_SECRET in .env).\n"
    "    from django.conf import settings as _kl_settings\n"
    "    if views and getattr(_kl_settings, 'KOOPLIJST_SECRET', ''):\n"
    "        views.append({\n"
    "            'id': 'kooplijst',\n"
    "            'label': 'Kooplijst',\n"
    "            'url_name': 'quotes:kooplijst',\n"
    "            'icon': '🛒',\n"
    "        })\n"
    "\n"
)
BACKUP_BLOK = (
    "# Kooplijst: eigen database + instellingen mee in de backup (in config/, dus zonder de tar-regel te wijzigen)\n"
    "KOOP_DIR=\"${KOOP_DIR:-/Users/Shared/terra-kooplijst}\"\n"
    "if \"$PGBIN/psql\" \"${PGC[@]}\" -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='terra_kooplijst'\" 2>/dev/null | grep -q 1; then\n"
    "  mkdir -p \"$WORK/config/kooplijst\"\n"
    "  \"$PGBIN/pg_dump\" \"${PGC[@]}\" -Fc terra_kooplijst -f \"$WORK/config/kooplijst/kooplijst.dump\" 2>>\"$LOG\" \\\n"
    "    && log \"kooplijst: database $(du -k \"$WORK/config/kooplijst/kooplijst.dump\" | cut -f1) kB\" || log \"let op: dump kooplijst mislukt\"\n"
    "  cp \"$KOOP_DIR/.env\" \"$WORK/config/kooplijst/env\" 2>/dev/null\n"
    "fi\n"
    "\n"
)
KOPIEER = ('kooplijst_views.py', 'test_kooplijst.py')


class PlekOntbreekt(Exception):
    pass


def _lees(pad):
    return pad.read_text(encoding='utf-8')


def _eigenaar_als(pad, voorbeeld):
    """Als beheerder (root) gedraaid: nieuwe bestanden krijgen de eigenaar van de map waar ze in komen."""
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        st = voorbeeld.stat()
        for p in [pad] + (list(pad.rglob('*')) if pad.is_dir() else []):
            try:
                os.chown(p, st.st_uid, st.st_gid)
            except OSError:
                pass


def plan_urls(tekst):
    if 'kooplijst_views' in tekst:
        return None
    if tekst.count('urlpatterns = [\n') != 1:
        raise PlekOntbreekt("quotes/urls.py: de regel 'urlpatterns = [' staat er niet precies één keer")
    if 'path(' not in tekst:
        raise PlekOntbreekt("quotes/urls.py: 'path' wordt niet gebruikt (andere opzet dan verwacht)")
    return tekst.replace('urlpatterns = [\n', URLS_IMPORT + 'urlpatterns = [\n' + URLS_ROUTES, 1)


def plan_settings(tekst):
    if 'KOOPLIJST_SECRET' in tekst:
        return None
    if 'from decouple import' not in tekst or 'config(' not in tekst:
        raise PlekOntbreekt("terra_quotes/settings.py: 'config' van python-decouple wordt niet gebruikt")
    return tekst.rstrip('\n') + '\n' + SETTINGS_BLOK


def plan_knop(tekst):
    """Mag ontbreken: zonder knop is de kooplijst nog bereikbaar via /kooplijst/."""
    if "'quotes:kooplijst'" in tekst:
        return None
    begin = tekst.find('def get_user_allowed_views(')
    if begin < 0:
        raise PlekOntbreekt('functie get_user_allowed_views niet gevonden')
    einde = tekst.find('\ndef ', begin + 1)
    einde = len(tekst) if einde < 0 else einde
    plek = tekst.rfind('\n    return views\n', begin, einde + 1)
    if plek < 0:
        raise PlekOntbreekt("'return views' niet gevonden in get_user_allowed_views")
    return tekst[:plek + 1] + KNOP_BLOK + tekst[plek + 1:]


def plan_backup(tekst):
    """Mag ontbreken: dan staat de kooplijst-database niet in de TerraFlow-backup (de installatie meldt dat)."""
    if 'terra_kooplijst' in tekst:
        return None
    for nodig in ('"$PGBIN/pg_dump"', 'PGC=(', '$WORK', '$LOG', 'log '):
        if nodig not in tekst:
            raise PlekOntbreekt(f'backup.sh gebruikt {nodig} niet (andere opzet dan verwacht)')
    if tekst.count('\n# 2) media\n') != 1:
        raise PlekOntbreekt("de regel '# 2) media' staat er niet precies één keer")
    return tekst.replace('\n# 2) media\n', '\n' + BACKUP_BLOK + '# 2) media\n', 1)


BESTANDEN = (       # (pad, planner, verplicht)
    ('quotes/urls.py', plan_urls, True),
    ('terra_quotes/settings.py', plan_settings, True),
    ('quotes/services/project_helpers.py', plan_knop, False),
    ('deploy/macos/backup.sh', plan_backup, False),
)


def maak_plan(app, koop):
    """Geeft (wijzigingen, kopieën, meldingen, fouten) zonder iets te schrijven."""
    wijzigingen, kopieen, meldingen, fouten = [], [], [], []
    for rel, planner, verplicht in BESTANDEN:
        pad = app / rel
        if not pad.is_file():
            (fouten if verplicht else meldingen).append(f'{rel}: bestand ontbreekt')
            continue
        try:
            nieuw = planner(_lees(pad))
        except PlekOntbreekt as e:
            (fouten if verplicht else meldingen).append(f'{rel}: {e}' if rel not in str(e) else str(e))
            continue
        if nieuw is not None:
            wijzigingen.append((rel, nieuw))
    for naam in KOPIEER:
        bron, doel = koop / 'terraflow' / naam, app / 'quotes' / naam
        if not bron.is_file():
            fouten.append(f'terraflow/{naam} ontbreekt in de kooplijst-map')
        elif not doel.is_file() or _lees(doel) != _lees(bron):
            kopieen.append((f'quotes/{naam}', bron))
    return wijzigingen, kopieen, meldingen, fouten


def status(app, koop):
    wijzigingen, kopieen, meldingen, fouten = maak_plan(app, koop)
    for f in fouten:
        print('FOUT', f)
    for m in meldingen:
        print('OVERGESLAGEN', m)
    for rel, _ in wijzigingen:
        print('ONTBREEKT', rel)
    for rel, _ in kopieen:
        print('ONTBREEKT', rel)
    if fouten:
        return 2
    print('COMPLEET' if not wijzigingen and not kopieen else 'NODIG')
    return 0


def toepas(app, koop):
    wijzigingen, kopieen, meldingen, fouten = maak_plan(app, koop)
    for m in meldingen:
        print('OVERGESLAGEN', m)
    if fouten:
        for f in fouten:
            print('FOUT', f)
        print('Er is niets gewijzigd.')
        return 2
    if not wijzigingen and not kopieen:
        print('COMPLEET')
        return 0
    # Eerst nagaan of alles geschreven kan worden; anders niets aanraken.
    dicht = [rel for rel, _ in list(wijzigingen) + list(kopieen)
             if not os.access(app / rel if (app / rel).exists() else (app / rel).parent, os.W_OK)]
    if dicht:
        for rel in dicht:
            print('GEEN-SCHRIJFRECHT', rel)
        print('Er is niets gewijzigd.')
        return 3
    backup = koop / '.koppeling-backup' / time.strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True, exist_ok=True)
    nieuw_aangemaakt = []
    for rel, _ in list(wijzigingen) + list(kopieen):
        bron = app / rel
        if bron.is_file():
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bron, backup / rel)
        else:
            nieuw_aangemaakt.append(rel)
    (backup / 'NIEUW.txt').write_text('\n'.join(nieuw_aangemaakt), encoding='utf-8')
    _eigenaar_als(koop / '.koppeling-backup', koop)
    print('BACKUP', backup)
    try:
        for rel, nieuw in wijzigingen:
            (app / rel).write_text(nieuw, encoding='utf-8', newline='\n')
            print('GEWIJZIGD', rel)
        for rel, bron in kopieen:
            shutil.copyfile(bron, app / rel)
            _eigenaar_als(app / rel, (app / rel).parent)
            print('GEWIJZIGD', rel)
    except OSError as e:
        print('FOUT', e)
        terug(app, backup)          # halverwege mislukt: alles terug naar hoe het was
        print('Alles is teruggezet.')
        return 1
    return 0


def terug(app, backup):
    if not backup.is_dir():
        print('FOUT backup-map ontbreekt:', backup)
        return 1
    nieuw = [r for r in (backup / 'NIEUW.txt').read_text(encoding='utf-8').splitlines() if r.strip()] if (backup / 'NIEUW.txt').is_file() else []
    for pad in backup.rglob('*'):
        if pad.is_file() and pad.name != 'NIEUW.txt':
            rel = pad.relative_to(backup)
            shutil.copy2(pad, app / rel)
            print('TERUGGEZET', rel)
    for rel in nieuw:
        doel = app / rel
        if doel.is_file():
            doel.unlink()
            print('VERWIJDERD', rel)
    return 0


def main(argv):
    if len(argv) != 4 or argv[1] not in ('status', 'toepas', 'terug'):
        print(__doc__)
        return 1
    app, tweede = Path(argv[2]), Path(argv[3])
    if not (app / 'manage.py').is_file() or not (app / 'quotes').is_dir():
        print('FOUT geen TerraFlow-map:', app)
        return 1
    try:
        return {'status': status, 'toepas': toepas, 'terug': terug}[argv[1]](app, tweede)
    except OSError as e:
        print('FOUT', e)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
