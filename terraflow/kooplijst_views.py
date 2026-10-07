"""
Kooplijst (github.com/nvoostenbrugge/terra-kooplijst) binnen TerraFlow.

De kooplijst is een losse Django-dienst op de Mac (poort 8091, eigen database terra_kooplijst),
zelfde opzet als het sales dashboard. TerraFlow zet hem achter de eigen login op /kooplijst/ en
geeft bij elk verzoek mee wie er kijkt:

    X-TerraFlow-Secret   gedeeld geheim (KOOPLIJST_SECRET in beide .env-bestanden)
    X-TerraFlow-User     e-mailadres van de ingelogde gebruiker
    X-TerraFlow-Name     volledige naam
    X-TerraFlow-Admin    "1" voor super-admins

De kooplijst heeft dus geen eigen login en weigert elk verzoek zonder het geheim. Wie mag
goedkeuren of bestellen wordt in de kooplijst zelf ingesteld (knop Beheer, alleen super-admins).

Andersom vraagt de kooplijst via /api/internal/kooplijst/push/ om een pushmelding; dat verzoek
draagt hetzelfde geheim. Zo blijven de apparaten en VAPID-sleutels in TerraFlow.

Zolang KOOPLIJST_SECRET leeg is (niet geïnstalleerd) bestaat de knop "Kooplijst" niet en geeft
/kooplijst/ een nette melding.

Dit bestand hoort bij de kooplijst-repo (map terraflow/) en wordt door diens installatie naar
quotes/ gekopieerd; de routes, instellingen en de knop zet deploy/macos/koppel_terraflow.py erbij.
Wijzigingen dus in de kooplijst-repo doen, niet hier.
"""
import hmac
import json
import logging

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

logger = logging.getLogger(__name__)

PREFIX = '/kooplijst'
_DOORGEVEN = ('cache-control', 'etag', 'last-modified', 'expires', 'vary', 'content-disposition')


def _upstream():
    return getattr(settings, 'KOOPLIJST_UPSTREAM', 'http://127.0.0.1:8091').rstrip('/')


def _secret():
    return getattr(settings, 'KOOPLIJST_SECRET', '') or ''


def _melding(titel, tekst, status):
    return HttpResponse(
        '<!doctype html><meta charset="utf-8"><body style="font-family:system-ui;padding:40px;color:#334155">'
        f'<h2>{titel}</h2><p>{tekst}</p><p><a href="/">&larr; Terug naar TerraFlow</a></p></body>', status=status)


@ensure_csrf_cookie            # de pagina van de kooplijst stuurt bij elke POST het csrftoken-cookie als X-CSRFToken mee
@require_http_methods(['GET', 'POST'])
@login_required
def kooplijst_proxy(request, path=''):
    """Stuurt /kooplijst/<path> door naar de kooplijst-dienst; alleen voor ingelogde gebruikers."""
    secret = _secret()
    if not secret:
        return _melding('Kooplijst is nog niet geïnstalleerd',
                        'Op de Mac mini: dubbelklik "Kooplijst installeren.command" (in de map van de kooplijst).', 404)
    from quotes.services.project_helpers import is_super_admin
    user = request.user
    headers = {
        'X-TerraFlow-Secret': secret,
        'X-TerraFlow-User': (user.email or user.get_username()).lower(),
        'X-TerraFlow-Name': (user.get_full_name() or '').strip(),
        'X-TerraFlow-Admin': '1' if is_super_admin(user) else '0',
        'X-Forwarded-Prefix': PREFIX,
        'Accept': request.META.get('HTTP_ACCEPT', '*/*'),
    }
    for naam in ('HTTP_IF_NONE_MATCH', 'HTTP_IF_MODIFIED_SINCE'):
        if request.META.get(naam):
            headers[naam[5:].replace('_', '-').title()] = request.META[naam]
    url = f'{_upstream()}/{path}'
    if request.META.get('QUERY_STRING'):
        url += '?' + request.META['QUERY_STRING']
    kwargs = {}
    if request.method == 'POST':
        if (request.content_type or '').startswith('multipart/'):
            # De CSRF-controle heeft het formulier al uitgelezen; opnieuw opbouwen voor de dienst.
            kwargs['data'] = request.POST.dict()
            kwargs['files'] = {naam: (f.name, f, f.content_type or 'application/octet-stream') for naam, f in request.FILES.items()}
        else:
            headers['Content-Type'] = request.content_type or 'application/json'
            kwargs['data'] = request.body
    try:
        upstream = requests.request(request.method, url, headers=headers, allow_redirects=False, timeout=60, **kwargs)
    except requests.RequestException as e:
        logger.warning('kooplijst niet bereikbaar: %s', e)
        if path.startswith('api/'):
            return JsonResponse({'fout': 'De kooplijst-dienst reageert niet. Probeer het over een minuut opnieuw.'}, status=502)
        return _melding('Kooplijst is niet bereikbaar',
                        'De kooplijst-dienst draait niet (of start nog). Probeer het over een minuut opnieuw '
                        'of vraag de beheerder om "Herstart TerraFlow".', 502)
    resp = HttpResponse(upstream.content, status=upstream.status_code,
                        content_type=upstream.headers.get('Content-Type', 'application/octet-stream'))
    for k, v in upstream.headers.items():
        if k.lower() in _DOORGEVEN:
            resp[k] = v
        elif k.lower() == 'location' and v.startswith('/') and not v.startswith(PREFIX):
            resp[k] = PREFIX + v
    return resp


@csrf_exempt                   # aangeroepen door de kooplijst-dienst zelf (geen browser); het gedeelde geheim is de sleutel
@require_POST
def kooplijst_push(request):
    """Pushmelding namens de kooplijst: {emails: [...], title, body, url, tag}."""
    secret = _secret()
    gegeven = request.headers.get('X-Kooplijst-Secret', '')
    if not secret or not gegeven or not hmac.compare_digest(gegeven, secret):
        return JsonResponse({'success': False, 'error': 'geen toegang'}, status=403)
    try:
        data = json.loads(request.body or b'{}')
        emails = sorted({str(e).strip().lower() for e in data.get('emails', []) if e})[:100]
        title, body = str(data.get('title') or '')[:120], str(data.get('body') or '')[:300]
    except (ValueError, AttributeError, TypeError):
        return JsonResponse({'success': False, 'error': 'ongeldige aanvraag'}, status=400)
    if not emails or not title:
        return JsonResponse({'success': False, 'error': 'emails en title zijn verplicht'}, status=400)
    url = str(data.get('url') or '')
    if not url.startswith(PREFIX + '/'):       # meldingen van de kooplijst openen alleen de kooplijst
        url = PREFIX + '/'
    User = get_user_model()
    user_ids = set(User.objects.annotate(e=Lower('email')).filter(e__in=emails, is_active=True).values_list('id', flat=True))
    try:    # aliassen (meerdere adressen per account) staan in allauth
        from allauth.account.models import EmailAddress
        user_ids |= set(EmailAddress.objects.annotate(e=Lower('email')).filter(e__in=emails, user__is_active=True)
                        .values_list('user_id', flat=True))
    except Exception:  # noqa: BLE001
        pass
    from quotes.services.push_helpers import send_push_to_users
    result = send_push_to_users(User.objects.filter(id__in=user_ids), title=title, body=body, url=url,
                                tag=str(data.get('tag') or 'kooplijst')[:60])
    return JsonResponse({'success': True, 'users_found': len(user_ids), **result})
