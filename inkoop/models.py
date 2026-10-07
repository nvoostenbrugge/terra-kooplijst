from django.db import models
from django.utils import timezone


class Gebruiker(models.Model):
    """Iemand die de kooplijst via TerraFlow heeft geopend. Het e-mailadres komt van TerraFlow."""
    email = models.CharField(max_length=254, unique=True)
    naam = models.CharField(max_length=200, blank=True, default='')
    is_admin = models.BooleanField(default=False, help_text='Super-admin in TerraFlow (zoals laatst doorgegeven)')
    mag_goedkeuren = models.BooleanField(default=False)
    mag_bestellen = models.BooleanField(default=False)
    laatst_gezien = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['naam', 'email']

    def __str__(self):
        return self.naam or self.email

    @property
    def goedkeurder(self):
        return self.is_admin or self.mag_goedkeuren

    @property
    def besteller(self):
        return self.is_admin or self.mag_bestellen

    @property
    def ziet_alles(self):
        """Alleen wie goedkeurt of bestelt ziet de hele lijst; ieder ander alleen eigen aanvragen."""
        return self.goedkeurder or self.besteller

    @property
    def toon_naam(self):
        return self.naam or self.email.split('@')[0]


class Bestelling(models.Model):
    """Eén order bij één winkel: alle regels die in één keer besteld zijn."""
    winkel = models.CharField(max_length=200, blank=True, default='')
    ordernr = models.CharField(max_length=200, blank=True, default='')
    besteld_op = models.DateTimeField(default=timezone.now)
    besteld_door = models.ForeignKey(Gebruiker, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    tracking_url = models.URLField(max_length=1000, blank=True, default='')
    vervoerder = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        ordering = ['-besteld_op', '-id']


class Regel(models.Model):
    AANGEVRAAGD, GOEDGEKEURD, BESTELD, ONTVANGEN, AFGEWEZEN = 'aangevraagd', 'goedgekeurd', 'besteld', 'ontvangen', 'afgewezen'
    STATUSSEN = [(AANGEVRAAGD, 'Wacht op akkoord'), (GOEDGEKEURD, 'Akkoord'), (BESTELD, 'Besteld'),
                 (ONTVANGEN, 'Ontvangen'), (AFGEWEZEN, 'Afgewezen')]

    aanvrager = models.ForeignKey(Gebruiker, null=True, blank=True, on_delete=models.SET_NULL, related_name='regels')
    aanvrager_naam = models.CharField(max_length=200, blank=True, default='',
                                      help_text='Naam uit de oude kooplijst, als er nog geen gebruiker aan gekoppeld is')
    omschrijving = models.CharField(max_length=500, blank=True, default='')
    link = models.CharField(max_length=2000, blank=True, default='')
    winkel = models.CharField(max_length=200, blank=True, default='', db_index=True)
    aantal = models.PositiveIntegerField(default=1)
    per_verpakking = models.PositiveIntegerField(default=1)
    prijs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text='Totaalprijs in euro')
    project = models.CharField(max_length=200, blank=True, default='')
    opmerking = models.CharField(max_length=500, blank=True, default='')
    spoed = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUSSEN, default=AANGEVRAAGD, db_index=True)

    aangevraagd_op = models.DateTimeField(default=timezone.now)
    goedgekeurd_op = models.DateTimeField(null=True, blank=True)
    goedgekeurd_door = models.ForeignKey(Gebruiker, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    ontvangen_op = models.DateTimeField(null=True, blank=True)
    bestelling = models.ForeignKey(Bestelling, null=True, blank=True, on_delete=models.SET_NULL, related_name='regels')
    factuurnr = models.CharField(max_length=200, blank=True, default='')
    geimporteerd = models.BooleanField(default=False, help_text='Overgezet uit de oude Excel-kooplijst')

    # Resultaat van het vullen van de winkelwagen (door Claude op de pc van de besteller)
    wagen_ok = models.BooleanField(null=True, blank=True)
    wagen_notitie = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ['-aangevraagd_op', '-id']

    def __str__(self):
        return f'{self.aantal}x {self.omschrijving}'


class Wagen(models.Model):
    """Een gevulde winkelwagen bij één winkel, klaar om af te rekenen."""
    winkel = models.CharField(max_length=200, unique=True)
    url = models.URLField(max_length=1000, blank=True, default='')
    notitie = models.CharField(max_length=300, blank=True, default='')
    gevuld_op = models.DateTimeField(default=timezone.now)


class Instelling(models.Model):
    sleutel = models.CharField(max_length=100, unique=True)
    waarde = models.JSONField(default=dict)

    BESTELMOMENTEN = 'bestelmomenten'
    STANDAARD = {BESTELMOMENTEN: {'dagen': [0, 2], 'ronde_uur': 14, 'vul_uur': 13}}   # ma + wo, ronde 14:00

    @classmethod
    def haal(cls, sleutel):
        rij = cls.objects.filter(sleutel=sleutel).first()
        return {**cls.STANDAARD.get(sleutel, {}), **(rij.waarde if rij else {})}

    @classmethod
    def zet(cls, sleutel, waarde):
        cls.objects.update_or_create(sleutel=sleutel, defaults={'waarde': waarde})


class MeldingLog(models.Model):
    """Welke pushmeldingen al verstuurd zijn, zodat dezelfde melding nooit twee keer gaat."""
    sleutel = models.CharField(max_length=200, unique=True)
    verstuurd_op = models.DateTimeField(default=timezone.now)
