"""Pushmeldingen lopen via TerraFlow: die kent de apparaten van iedereen en verstuurt de melding."""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def stuur(emails, titel, tekst, url='/kooplijst/', tag=None):
    """Vraag TerraFlow om een push naar deze e-mailadressen. True als TerraFlow het verzoek aannam.

    Faalt nooit hard: een melding die niet lukt mag een aanvraag of bestelling niet tegenhouden.
    """
    emails = sorted({e.lower() for e in emails if e})
    if not emails:
        return True
    if not settings.TERRAFLOW_SECRET:
        logger.info('push overgeslagen (geen TERRAFLOW_SECRET): %s', titel)
        return False
    try:
        r = requests.post(
            f'{settings.TERRAFLOW_URL}/api/internal/kooplijst/push/',
            json={'emails': emails, 'title': titel[:120], 'body': tekst[:300], 'url': url, 'tag': tag or 'kooplijst'},
            headers={'X-Kooplijst-Secret': settings.TERRAFLOW_SECRET},
            timeout=6,
        )
    except requests.RequestException as e:
        logger.warning('push mislukt (TerraFlow niet bereikbaar): %s', e)
        return False
    if r.status_code != 200:
        logger.warning('push geweigerd door TerraFlow (HTTP %s): %s', r.status_code, r.text[:200])
        return False
    return True
