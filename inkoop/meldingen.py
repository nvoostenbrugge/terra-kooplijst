"""
Wanneer gaat er een pushmelding uit, en naar wie?

Direct (vanuit een actie in de app):
  - spoedaanvraag ingediend            -> wie mag goedkeuren
  - spoedaanvraag goedgekeurd          -> wie mag bestellen
  - besteld                            -> de aanvrager
  - volglink toegevoegd                -> de aanvrager

Periodiek (management-commando kooplijst_meldingen, elk kwartier op werkdagen 8-18 uur):
  - nieuwe gewone aanvragen, gebundeld -> wie mag goedkeuren
  - langer dan 2 werkdagen wachten     -> wie mag goedkeuren (hooguit 1x per dag)
  - goedgekeurd maar ronde gemist      -> wie mag bestellen (1x per gemiste ronde)
"""
from django.db.models import Q
from django.utils import timezone

from . import logica, push
from .models import Gebruiker, Instelling, MeldingLog, Regel


def _emails(filter_q, zonder=None):
    qs = Gebruiker.objects.filter(filter_q)
    if zonder is not None:
        qs = qs.exclude(pk=zonder.pk)
    return list(qs.values_list('email', flat=True))


def goedkeurders(zonder=None):
    return _emails(Q(is_admin=True) | Q(mag_goedkeuren=True), zonder)


def bestellers(zonder=None):
    return _emails(Q(is_admin=True) | Q(mag_bestellen=True), zonder)


def _nog_niet(sleutels):
    al = set(MeldingLog.objects.filter(sleutel__in=sleutels).values_list('sleutel', flat=True))
    return [s for s in sleutels if s not in al]


def _log(sleutels):
    MeldingLog.objects.bulk_create([MeldingLog(sleutel=s) for s in sleutels], ignore_conflicts=True)


def _opsomming(regels, maximum=3):
    namen = [f'{r.aantal}× {r.omschrijving or "artikel"}' for r in regels[:maximum]]
    rest = len(regels) - len(namen)
    return ', '.join(namen) + (f' en {rest} meer' if rest > 0 else '')


def _aanvrager_naam(regel):
    return regel.aanvrager.toon_naam if regel.aanvrager else (regel.aanvrager_naam or 'Iemand')


# ---------- direct ----------

def bij_nieuwe_aanvraag(regel):
    if not regel.spoed:
        return
    if push.stuur(goedkeurders(zonder=regel.aanvrager), 'Spoed: aanvraag wacht op akkoord',
                  f'{_aanvrager_naam(regel)}: {regel.aantal}× {regel.omschrijving}', '/kooplijst/#goedkeuren', f'kl-nieuw-{regel.pk}'):
        _log([f'nieuw:{regel.pk}'])


def bij_akkoord(regels, door):
    spoed = [r for r in regels if r.spoed]
    if spoed:
        push.stuur(bestellers(zonder=door), 'Spoed: bestellen', _opsomming(spoed), '/kooplijst/#bestellen', 'kl-spoed-bestellen')


def bij_besteld(bestelling, regels, door):
    per_aanvrager = {}
    for r in regels:
        if r.aanvrager_id and r.aanvrager_id != door.pk:
            per_aanvrager.setdefault(r.aanvrager, []).append(r)
    for aanvrager, eigen in per_aanvrager.items():
        push.stuur([aanvrager.email], f'Besteld bij {bestelling.winkel or "de winkel"}', _opsomming(eigen),
                   '/kooplijst/#onderweg', f'kl-besteld-{bestelling.pk}')


def bij_volglink(bestelling, door):
    per_aanvrager = {}
    for r in bestelling.regels.filter(status=Regel.BESTELD).select_related('aanvrager'):
        if r.aanvrager_id and r.aanvrager_id != door.pk:
            per_aanvrager.setdefault(r.aanvrager, []).append(r)
    for aanvrager, eigen in per_aanvrager.items():
        push.stuur([aanvrager.email], f'Onderweg: {bestelling.winkel or "je bestelling"}',
                   _opsomming(eigen) + '. Tik om je pakket te volgen.', '/kooplijst/#onderweg', f'kl-onderweg-{bestelling.pk}')


# ---------- periodiek ----------

def periodiek(nu=None):
    """Verstuur de gebundelde meldingen. Geeft terug hoeveel meldingen er verstuurd zijn."""
    nu = nu or timezone.now()
    lokaal = timezone.localtime(nu)
    if lokaal.weekday() >= 5 or not (8 <= lokaal.hour < 18):
        return 0
    verstuurd = 0

    # 1) nieuwe gewone aanvragen, gebundeld in één melding
    wachtend = list(Regel.objects.filter(status=Regel.AANGEVRAAGD).select_related('aanvrager').order_by('aangevraagd_op'))
    nieuw = {f'nieuw:{r.pk}': r for r in wachtend}
    open_sleutels = _nog_niet(list(nieuw))
    if open_sleutels:
        regels = [nieuw[s] for s in open_sleutels]
        titel = '1 nieuwe aanvraag' if len(regels) == 1 else f'{len(regels)} nieuwe aanvragen'
        if push.stuur(goedkeurders(), titel + ' op de kooplijst', _opsomming(regels), '/kooplijst/#goedkeuren', 'kl-nieuw'):
            _log(open_sleutels)
            verstuurd += 1

    # 2) langer dan 2 werkdagen wachten op akkoord: hooguit één melding per dag
    te_lang = [r for r in wachtend if logica.wacht_te_lang(r, nu)]
    if te_lang:
        dag = lokaal.date().isoformat()
        sleutels = {f'wacht:{r.pk}:{dag}': r for r in te_lang}
        open_sleutels = _nog_niet(list(sleutels))
        if open_sleutels:
            regels = [sleutels[s] for s in open_sleutels]
            titel = (f'{len(regels)} aanvragen wachten' if len(regels) > 1 else '1 aanvraag wacht') + ' al meer dan 2 werkdagen'
            if push.stuur(goedkeurders(), titel, _opsomming(regels), '/kooplijst/#goedkeuren', 'kl-wacht'):
                _log(open_sleutels)
                verstuurd += 1

    # 3) goedgekeurd, maar de bestelronde is voorbijgegaan zonder dat het besteld is
    ronde = logica.laatste_ronde(Instelling.haal(Instelling.BESTELMOMENTEN), nu)
    if ronde:
        gemist = [r for r in Regel.objects.filter(status=Regel.GOEDGEKEURD) if logica.ronde_gemist(r, ronde)]
        sleutels = {f'ronde:{r.pk}:{timezone.localtime(ronde).date().isoformat()}': r for r in gemist}
        open_sleutels = _nog_niet(list(sleutels))
        if open_sleutels:
            regels = [sleutels[s] for s in open_sleutels]
            titel = (f'{len(regels)} artikelen zijn' if len(regels) > 1 else '1 artikel is') + ' de bestelronde gemist'
            if push.stuur(bestellers(), titel, _opsomming(regels), '/kooplijst/#bestellen', 'kl-ronde'):
                _log(open_sleutels)
                verstuurd += 1
    return verstuurd
