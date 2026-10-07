"""Pagina en JSON-API van de kooplijst. Wie wat mag staat bovenaan elke view; wie wat ziet in _zichtbaar()."""
import json
from functools import wraps

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import importeren, logica, meldingen
from .models import Bestelling, Gebruiker, Instelling, Regel, Wagen

AFGEROND = (Regel.ONTVANGEN, Regel.AFGEWEZEN)
MAX_AFGEROND = 500


def fout(tekst, status=400):
    return JsonResponse({'fout': tekst}, status=status)


def vereist(recht):
    """recht: 'goedkeurder', 'besteller', 'ziet_alles' of 'is_admin' (eigenschap van Gebruiker)."""
    def decorator(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if not getattr(request.gebruiker, recht):
                return fout('Daar heb je geen rechten voor.', 403)
            return view(request, *args, **kwargs)
        return inner
    return decorator


def _body(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _tekst(data, sleutel, maximum):
    return str(data.get(sleutel) or '').strip()[:maximum]


def _getal(data, sleutel, standaard=1):
    try:
        return max(1, min(int(data.get(sleutel) or standaard), 1000000))
    except (TypeError, ValueError):
        return standaard


def _dag(moment):
    return timezone.localtime(moment).date().isoformat() if moment else ''


# ---------- zichtbaarheid en weergave ----------

def _zichtbaar(gebruiker):
    """Engineers zien alleen hun eigen aanvragen; goedkeurders en bestellers zien alles."""
    qs = Regel.objects.select_related('aanvrager', 'bestelling')
    return qs if gebruiker.ziet_alles else qs.filter(aanvrager=gebruiker)


def _regel_json(r, gebruiker, nu, ronde):
    staf = gebruiker.ziet_alles
    return {
        'id': r.pk,
        'omschrijving': r.omschrijving, 'link': r.link, 'winkel': r.winkel,
        'aantal': r.aantal, 'perVerpakking': r.per_verpakking,
        'prijs': float(r.prijs) if r.prijs is not None else None,
        'project': r.project, 'opmerking': r.opmerking, 'spoed': r.spoed, 'status': r.status,
        'aanvrager': r.aanvrager.toon_naam if r.aanvrager else r.aanvrager_naam,
        'aanvragerId': r.aanvrager_id, 'eigen': r.aanvrager_id == gebruiker.pk,
        'aangevraagdOp': _dag(r.aangevraagd_op), 'goedgekeurdOp': _dag(r.goedgekeurd_op), 'ontvangenOp': _dag(r.ontvangen_op),
        'bestellingId': r.bestelling_id,
        'besteldOp': _dag(r.bestelling.besteld_op) if r.bestelling else '',
        'ordernr': r.bestelling.ordernr if r.bestelling else '',
        'factuurnr': r.factuurnr if staf else '',
        'wagenOk': r.wagen_ok if staf else None, 'wagenNotitie': r.wagen_notitie if staf else '',
        'wachtTeLang': logica.wacht_te_lang(r, nu),
        'rondeGemist': logica.ronde_gemist(r, ronde),
    }


def _staat(gebruiker):
    nu = timezone.now()
    momenten = Instelling.haal(Instelling.BESTELMOMENTEN)
    ronde = logica.laatste_ronde(momenten, nu)
    zichtbaar = _zichtbaar(gebruiker)
    regels = list(zichtbaar.exclude(status__in=AFGEROND)) + list(zichtbaar.filter(status__in=AFGEROND)[:MAX_AFGEROND])
    bestelling_ids = {r.bestelling_id for r in regels if r.bestelling_id}
    staat = {
        'ik': {'id': gebruiker.pk, 'email': gebruiker.email, 'naam': gebruiker.toon_naam, 'admin': gebruiker.is_admin,
               'goedkeuren': gebruiker.goedkeurder, 'bestellen': gebruiker.besteller, 'zietAlles': gebruiker.ziet_alles},
        'regels': [_regel_json(r, gebruiker, nu, ronde) for r in regels],
        'bestellingen': [{'id': b.pk, 'winkel': b.winkel, 'ordernr': b.ordernr, 'besteldOp': _dag(b.besteld_op),
                          'tracking': b.tracking_url, 'vervoerder': b.vervoerder}
                         for b in Bestelling.objects.filter(pk__in=bestelling_ids)],
        'momenten': momenten,
        'versie': settings.VERSION,
    }
    if gebruiker.ziet_alles:
        staat['wagens'] = {w.winkel: {'url': w.url, 'notitie': w.notitie, 'gevuldOp': _dag(w.gevuld_op)} for w in Wagen.objects.all()}
        staat['gebruikers'] = [{'id': g.pk, 'naam': g.toon_naam, 'email': g.email, 'admin': g.is_admin,
                                'goedkeuren': g.mag_goedkeuren, 'bestellen': g.mag_bestellen} for g in Gebruiker.objects.all()]
        staat['losseNamen'] = sorted(set(Regel.objects.filter(aanvrager__isnull=True).exclude(aanvrager_naam='')
                                         .exclude(status__in=AFGEROND).values_list('aanvrager_naam', flat=True)))
    return staat


def _klaar(request, **extra):
    return JsonResponse({'ok': True, **extra, 'staat': _staat(request.gebruiker)})


# ---------- pagina ----------

@require_GET
def pagina(request):
    return render(request, 'inkoop/index.html', {'versie': settings.VERSION})


@require_GET
def health(request):
    return JsonResponse({'ok': True, 'versie': settings.VERSION})


@require_GET
def staat(request):
    return JsonResponse(_staat(request.gebruiker))


# ---------- aanvragen ----------

def _vul_regel(regel, data):
    regel.link = _tekst(data, 'link', 2000)
    regel.winkel = logica.winkel_van(regel.link)
    regel.omschrijving = _tekst(data, 'omschrijving', 500)
    regel.aantal = _getal(data, 'aantal')
    regel.per_verpakking = _getal(data, 'perVerpakking')
    regel.prijs = logica.naar_prijs(data.get('prijs'))
    regel.project = _tekst(data, 'project', 200)
    regel.opmerking = _tekst(data, 'opmerking', 500)
    regel.spoed = bool(data.get('spoed'))


@require_POST
def regel_nieuw(request):
    data = _body(request)
    regel = Regel(aanvrager=request.gebruiker)
    _vul_regel(regel, data)
    if not regel.omschrijving:
        return fout('Vul een omschrijving in.')
    regel.save()
    meldingen.bij_nieuwe_aanvraag(regel)
    return _klaar(request, id=regel.pk)


@require_POST
def regel_wijzig(request, pk):
    gebruiker = request.gebruiker
    regel = get_object_or_404(_zichtbaar(gebruiker), pk=pk)
    staf = gebruiker.ziet_alles
    if not staf and regel.status != Regel.AANGEVRAAGD:
        return fout('Deze aanvraag is al in behandeling. Vraag een besteller om hem aan te passen.', 403)
    data = _body(request)
    was_spoed = regel.spoed
    _vul_regel(regel, data)
    if staf:
        regel.factuurnr = _tekst(data, 'factuurnr', 200)
        if 'aanvragerId' in data:
            regel.aanvrager = Gebruiker.objects.filter(pk=data.get('aanvragerId') or 0).first()
        nieuw = data.get('status')
        if nieuw and nieuw != regel.status:
            if nieuw == Regel.BESTELD:
                return fout('Zet een artikel op besteld via het tabblad Bestellen.')
            if nieuw not in dict(Regel.STATUSSEN):
                return fout('Onbekende status.')
            besluit = (Regel.AANGEVRAAGD, Regel.GOEDGEKEURD, Regel.AFGEWEZEN)
            if regel.status in besluit and nieuw in besluit and not gebruiker.goedkeurder:
                return fout('Goedkeuren of afwijzen mag alleen wie daarvoor is aangewezen.', 403)
            if nieuw in (Regel.AANGEVRAAGD, Regel.GOEDGEKEURD, Regel.AFGEWEZEN):
                regel.bestelling = None
                regel.ontvangen_op = None
            if nieuw == Regel.GOEDGEKEURD and not regel.goedgekeurd_op:
                regel.goedgekeurd_op, regel.goedgekeurd_door = timezone.now(), gebruiker
            if nieuw == Regel.ONTVANGEN:
                regel.ontvangen_op = regel.ontvangen_op or timezone.now()
            regel.status = nieuw
    regel.save()
    if regel.spoed and not was_spoed and regel.status == Regel.AANGEVRAAGD:
        meldingen.bij_nieuwe_aanvraag(regel)
    return _klaar(request)


# ---------- goedkeuren ----------

def _keur_goed(regels, gebruiker):
    nu = timezone.now()
    for r in regels:
        r.status, r.goedgekeurd_op, r.goedgekeurd_door = Regel.GOEDGEKEURD, nu, gebruiker
        r.save(update_fields=['status', 'goedgekeurd_op', 'goedgekeurd_door'])
    meldingen.bij_akkoord(regels, gebruiker)


@require_POST
@vereist('goedkeurder')
def regel_akkoord(request, pk):
    regel = get_object_or_404(Regel, pk=pk, status=Regel.AANGEVRAAGD)
    _keur_goed([regel], request.gebruiker)
    return _klaar(request)


@require_POST
@vereist('goedkeurder')
def akkoord_alles(request):
    ids = _body(request).get('ids') or []
    regels = list(Regel.objects.filter(pk__in=[i for i in ids if isinstance(i, int)], status=Regel.AANGEVRAAGD))
    _keur_goed(regels, request.gebruiker)
    return _klaar(request, aantal=len(regels))


@require_POST
@vereist('goedkeurder')
def regel_afwijzen(request, pk):
    regel = get_object_or_404(Regel, pk=pk, status=Regel.AANGEVRAAGD)
    regel.status = Regel.AFGEWEZEN
    regel.save(update_fields=['status'])
    return _klaar(request)


# ---------- bestellen ----------

@require_POST
@vereist('besteller')
def besteld(request):
    data = _body(request)
    ids = [i for i in (data.get('ids') or []) if isinstance(i, int)]
    winkel = _tekst(data, 'winkel', 200)
    with transaction.atomic():
        regels = list(Regel.objects.select_for_update().filter(pk__in=ids, status=Regel.GOEDGEKEURD, winkel=winkel))
        if not regels or len(regels) != len(set(ids)):
            return fout('Deze artikelen zijn intussen gewijzigd. De lijst is ververst, probeer het opnieuw.', 409)
        bestelling = Bestelling.objects.create(winkel=winkel, ordernr=_tekst(data, 'ordernr', 200), besteld_door=request.gebruiker)
        for r in regels:
            r.status, r.bestelling, r.wagen_ok, r.wagen_notitie = Regel.BESTELD, bestelling, None, ''
            r.save(update_fields=['status', 'bestelling', 'wagen_ok', 'wagen_notitie'])
        if not Regel.objects.filter(status=Regel.GOEDGEKEURD, winkel=winkel).exists():
            Wagen.objects.filter(winkel=winkel).delete()
    regels = list(Regel.objects.filter(pk__in=ids).select_related('aanvrager'))
    meldingen.bij_besteld(bestelling, regels, request.gebruiker)
    return _klaar(request, aantal=len(regels))


@require_POST
@vereist('besteller')
def bestelling_volglink(request, pk):
    bestelling = get_object_or_404(Bestelling, pk=pk)
    url = _tekst(_body(request), 'url', 1000)
    if not url:
        bestelling.tracking_url, bestelling.vervoerder = '', ''
        bestelling.save(update_fields=['tracking_url', 'vervoerder'])
        return _klaar(request)
    vervoerder = logica.vervoerder_van(url)
    if not vervoerder:
        return fout('Dit is geen volglink van een bekende vervoerder (PostNL, DHL, DPD, UPS, GLS, FedEx). '
                    'Links uit een bestelmail of naar een account worden niet gedeeld.')
    nieuw = bestelling.tracking_url != logica.nette_link(url)
    bestelling.tracking_url, bestelling.vervoerder = logica.nette_link(url), vervoerder
    bestelling.save(update_fields=['tracking_url', 'vervoerder'])
    if nieuw:
        meldingen.bij_volglink(bestelling, request.gebruiker)
    return _klaar(request, vervoerder=vervoerder)


@require_POST
def ontvangen(request):
    """Afvinken wat binnen is: de aanvrager voor zijn eigen artikelen, bestellers en goedkeurders voor alles."""
    ids = [i for i in (_body(request).get('ids') or []) if isinstance(i, int)]
    regels = _zichtbaar(request.gebruiker).filter(pk__in=ids, status=Regel.BESTELD)
    aantal = regels.update(status=Regel.ONTVANGEN, ontvangen_op=timezone.now())
    return _klaar(request, aantal=aantal)


# ---------- winkelwagens (gevuld door Claude op de pc van de besteller) ----------

@require_POST
@vereist('besteller')
def wagen_melden(request):
    """Resultaat van het vullen van één winkelwagen: {winkel, url, notitie, regels: {id: {ok, notitie}}}."""
    data = _body(request)
    winkel = _tekst(data, 'winkel', 200)
    if not winkel:
        return fout('Winkel ontbreekt.')
    url = logica.nette_link(data.get('url'))
    if url and logica.winkel_van(url) != winkel:
        return fout('De link van de winkelwagen hoort niet bij deze winkel.')
    Wagen.objects.update_or_create(winkel=winkel, defaults={'url': url, 'notitie': _tekst(data, 'notitie', 300), 'gevuld_op': timezone.now()})
    for sleutel, uitkomst in (data.get('regels') or {}).items():
        if not str(sleutel).isdigit() or not isinstance(uitkomst, dict):
            continue
        Regel.objects.filter(pk=int(sleutel), winkel=winkel, status=Regel.GOEDGEKEURD).update(
            wagen_ok=bool(uitkomst.get('ok')), wagen_notitie=str(uitkomst.get('notitie') or '')[:300])
    return _klaar(request)


@require_GET
@vereist('besteller')
def vultaak(request):
    """Voor de Claude-taak op de pc van de besteller: moet er nu gevuld worden, en wat?"""
    momenten = Instelling.haal(Instelling.BESTELMOMENTEN)
    open_regels = list(Regel.objects.filter(status=Regel.GOEDGEKEURD, wagen_ok__isnull=True).exclude(link=''))
    nu_vullen = logica.vulmoment_nu(momenten) or any(r.spoed for r in open_regels)
    regels = open_regels if logica.vulmoment_nu(momenten) else [r for r in open_regels if r.spoed]
    return JsonResponse({
        'vullen': bool(nu_vullen and regels),
        'regels': [{'id': r.pk, 'winkel': r.winkel, 'link': logica.nette_link(r.link), 'aantal': r.aantal,
                    'omschrijving': r.omschrijving, 'opmerking': r.opmerking, 'spoed': r.spoed} for r in regels],
    })


@require_POST
@vereist('besteller')
def instellingen(request):
    data = _body(request)
    try:
        dagen = sorted({int(d) for d in data.get('dagen') or [] if 0 <= int(d) <= 6})
        ronde_uur, vul_uur = int(data.get('ronde_uur')), int(data.get('vul_uur'))
    except (TypeError, ValueError):
        return fout('Ongeldige bestelmomenten.')
    if not dagen or not (6 <= ronde_uur <= 20) or not (6 <= vul_uur <= 20):
        return fout('Kies minstens één dag en een tijd tussen 6 en 20 uur.')
    Instelling.zet(Instelling.BESTELMOMENTEN, {'dagen': dagen, 'ronde_uur': ronde_uur, 'vul_uur': vul_uur})
    return _klaar(request)


# ---------- beheer (super-admins van TerraFlow) ----------

@require_POST
@vereist('is_admin')
def team(request):
    data = _body(request)
    gebruiker = Gebruiker.objects.filter(pk=data.get('id') or 0).first()
    if not gebruiker:
        email = _tekst(data, 'email', 254).lower()
        if '@' not in email:
            return fout('Vul een geldig e-mailadres in.')
        gebruiker, _ = Gebruiker.objects.get_or_create(email=email)
    gebruiker.mag_goedkeuren = bool(data.get('goedkeuren'))
    gebruiker.mag_bestellen = bool(data.get('bestellen'))
    gebruiker.save(update_fields=['mag_goedkeuren', 'mag_bestellen'])
    return _klaar(request)


@require_POST
@vereist('is_admin')
def koppel_naam(request):
    """Naam uit de oude kooplijst aan een gebruiker hangen, zodat die zijn eigen regels ziet."""
    data = _body(request)
    gebruiker = get_object_or_404(Gebruiker, pk=data.get('id') or 0)
    naam = _tekst(data, 'naam', 200)
    aantal = Regel.objects.filter(aanvrager__isnull=True, aanvrager_naam=naam).update(aanvrager=gebruiker) if naam else 0
    return _klaar(request, aantal=aantal)


@require_POST
@vereist('is_admin')
def importeer(request):
    bestand = request.FILES.get('bestand')
    if not bestand:
        return fout('Kies het Excel-bestand van de kooplijst.')
    try:
        uitkomst = importeren.importeer_xlsx(bestand, proef=request.POST.get('proef') == '1')
    except importeren.ImportFout as e:
        return fout(str(e))
    return _klaar(request, **uitkomst)
