"""
Wie kijkt er? De kooplijst heeft geen eigen login: TerraFlow zet de dienst achter zijn login en
stuurt bij elk verzoek deze headers mee (zie quotes/kooplijst_views.py in TerraFlow):

    X-TerraFlow-Secret   gedeeld geheim, bewijst dat het verzoek via TerraFlow komt
    X-TerraFlow-User     e-mailadres van de ingelogde gebruiker
    X-TerraFlow-Name     volledige naam
    X-TerraFlow-Admin    "1" voor super-admins

Zonder kloppend geheim wordt elk verzoek geweigerd, behalve /health/.
"""
import hmac

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from .models import Gebruiker

OPEN_PADEN = ('/health/',)


class TerraFlowToegang:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in OPEN_PADEN or request.path.startswith('/static/'):
            return self.get_response(request)

        email, naam, admin = '', '', False
        geheim = request.headers.get('X-TerraFlow-Secret', '')
        if settings.TERRAFLOW_SECRET and geheim and hmac.compare_digest(geheim, settings.TERRAFLOW_SECRET):
            email = request.headers.get('X-TerraFlow-User', '').strip().lower()
            naam = request.headers.get('X-TerraFlow-Name', '').strip()
            admin = request.headers.get('X-TerraFlow-Admin', '') == '1'
        elif settings.DEV_USER:
            email, naam, admin = settings.DEV_USER.lower(), settings.DEV_USER.split('@')[0].title(), settings.DEV_ADMIN

        if not email:
            return self._geweigerd(request)

        gebruiker, nieuw = Gebruiker.objects.get_or_create(email=email, defaults={'naam': naam, 'is_admin': admin})
        velden = []
        if naam and gebruiker.naam != naam:
            gebruiker.naam = naam
            velden.append('naam')
        if gebruiker.is_admin != admin:
            gebruiker.is_admin = admin
            velden.append('is_admin')
        nu = timezone.now()
        if nieuw or not gebruiker.laatst_gezien or (nu - gebruiker.laatst_gezien).total_seconds() > 600:
            gebruiker.laatst_gezien = nu
            velden.append('laatst_gezien')
        if velden:
            gebruiker.save(update_fields=velden)
        request.gebruiker = gebruiker
        return self.get_response(request)

    @staticmethod
    def _geweigerd(request):
        if request.path.startswith('/api/'):
            return JsonResponse({'fout': 'Open de kooplijst via TerraFlow.'}, status=403)
        return HttpResponse('<!doctype html><meta charset="utf-8"><body style="font-family:system-ui;padding:40px">'
                            '<h2>Kooplijst</h2><p>Open de kooplijst via TerraFlow.</p></body>', status=403)
