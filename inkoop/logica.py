"""Regels van de kooplijst die niets met HTTP te maken hebben: winkels, werkdagen, bestelrondes, volglinks."""
import re
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

WACHT_WERKDAGEN = 2          # zo lang mag een aanvraag op akkoord wachten voordat er een melding gaat
RONDE_UITLOOP_UREN = 3       # zo lang na het begin van een bestelronde telt een artikel als "ronde gemist"


# ---------- links en winkels ----------

def nette_link(link):
    s = (link or '').strip()
    if not s:
        return ''
    if not re.match(r'https?://', s, re.I):
        if re.match(r'[a-z0-9-]+(\.[a-z0-9-]+)+/', s, re.I):
            s = 'https://' + s
        else:
            return ''
    try:
        p = urlparse(s)
    except ValueError:
        return ''
    return s if p.scheme in ('http', 'https') and p.hostname else ''


def winkel_van(link):
    url = nette_link(link)
    if not url:
        return ''
    host = urlparse(url).hostname.lower()
    while host.count('.') >= 2 and re.match(r'(www|nl|eu|shop|store)\.', host):
        host = host.split('.', 1)[1]
    return host


def naar_prijs(tekst):
    """'€ 1.400,00', '18,39' of '1,400.00' -> Decimal; leeg of onleesbaar -> None."""
    if tekst is None or isinstance(tekst, bool):
        return None
    if isinstance(tekst, (int, float, Decimal)):
        s = str(tekst)
    else:
        s = re.sub(r'[^\d.,-]', '', str(tekst))
        if not s:
            return None
        k, p = s.rfind(','), s.rfind('.')
        if k > -1 and p > -1:
            s = s.replace('.', '').replace(',', '.') if k > p else s.replace(',', '')
        elif k > -1:
            s = s.replace(',', '.')
    try:
        waarde = Decimal(s).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    return waarde if Decimal('0') <= waarde < Decimal('100000000') else None


# ---------- volglinks ----------

def vervoerder_van(url):
    """Naam van de vervoerder als de link bij een bekende vervoerder hoort, anders ''."""
    net = nette_link(url)
    if not net or not net.lower().startswith('https://'):
        return ''
    host = urlparse(net).hostname.lower()
    for domein, naam in settings.VERVOERDER_DOMEINEN.items():
        if host == domein or host.endswith('.' + domein):
            return naam
    return ''


# ---------- werkdagen en bestelrondes ----------

def werkdagen_tussen(begin, eind):
    """Aantal hele werkdagen (ma-vr) tussen twee momenten, in lokale tijd."""
    a, b = timezone.localtime(begin), timezone.localtime(eind)
    if b <= a:
        return 0
    dagen, dag = 0, a.date()
    while dag < b.date():
        dag += timedelta(days=1)
        if dag.weekday() < 5:
            dagen += 1
    # de laatste dag telt pas mee als het tijdstip van aanvragen gepasseerd is
    if dagen and b.date().weekday() < 5 and b.time() < a.time():
        dagen -= 1
    return dagen


def wacht_te_lang(regel, nu=None):
    nu = nu or timezone.now()
    return regel.status == 'aangevraagd' and werkdagen_tussen(regel.aangevraagd_op, nu) >= WACHT_WERKDAGEN


def laatste_ronde(momenten, nu=None):
    """Begin van de laatste bestelronde waarvan de uitloop voorbij is, of None."""
    nu = timezone.localtime(nu or timezone.now())
    dagen = set(momenten.get('dagen') or [])
    uur = int(momenten.get('ronde_uur', 14))
    for terug in range(0, 8):
        dag = nu.date() - timedelta(days=terug)
        if dag.weekday() not in dagen:
            continue
        begin = timezone.make_aware(datetime.combine(dag, time(uur, 0)), nu.tzinfo)
        if begin + timedelta(hours=RONDE_UITLOOP_UREN) <= nu:
            return begin
    return None


def ronde_gemist(regel, ronde):
    """Was dit artikel al goedgekeurd toen de laatste ronde begon, en is het nog steeds niet besteld?"""
    return bool(ronde and regel.status == 'goedgekeurd' and regel.goedgekeurd_op and regel.goedgekeurd_op <= ronde)


def vulmoment_nu(momenten, nu=None):
    """Is het nu het uur waarop de winkelwagens gevuld moeten worden?"""
    nu = timezone.localtime(nu or timezone.now())
    return nu.weekday() in set(momenten.get('dagen') or []) and nu.hour == int(momenten.get('vul_uur', 13))
