from django.core.management.base import BaseCommand

from inkoop import meldingen


class Command(BaseCommand):
    help = 'Verstuurt de gebundelde pushmeldingen van de kooplijst (elk kwartier gestart door launchd).'

    def handle(self, *args, **options):
        n = meldingen.periodiek()
        self.stdout.write(f'{n} melding(en) verstuurd')
