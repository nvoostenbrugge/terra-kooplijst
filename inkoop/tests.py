import io
import json
from datetime import datetime, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from . import logica, meldingen
from .importeren import importeer_xlsx
from .models import Bestelling, Gebruiker, Instelling, MeldingLog, Regel

GEHEIM = 'test-geheim'


def lokaal(jaar, maand, dag, uur=12, minuut=0):
    return timezone.make_aware(datetime(jaar, maand, dag, uur, minuut))


@override_settings(TERRAFLOW_SECRET=GEHEIM, DEV_USER='')
class Basis(TestCase):
    def setUp(self):
        self.push = mock.patch('inkoop.push.stuur', return_value=True).start()
        self.addCleanup(mock.patch.stopall)

    def als(self, email, admin=False, naam=''):
        return {'HTTP_X_TERRAFLOW_SECRET': GEHEIM, 'HTTP_X_TERRAFLOW_USER': email,
                'HTTP_X_TERRAFLOW_NAME': naam or email.split('@')[0].title(), 'HTTP_X_TERRAFLOW_ADMIN': '1' if admin else '0'}

    def post(self, pad, data, wie, **extra):
        return self.client.post(pad, json.dumps(data), content_type='application/json', **self.als(wie, **extra))

    def staat(self, wie, **extra):
        return self.client.get('/api/staat/', **self.als(wie, **extra)).json()

    def vraag_aan(self, wie, **velden):
        data = {'omschrijving': 'Servo', 'link': 'https://mini-zshop.nl/product/servo/', 'aantal': 2, 'prijs': '12,50', **velden}
        r = self.post('/api/regels/', data, wie)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['id']


class Toegang(Basis):
    def test_zonder_geheim_geen_toegang(self):
        self.assertEqual(self.client.get('/').status_code, 403)
        self.assertEqual(self.client.get('/api/staat/').status_code, 403)
        fout = self.client.get('/api/staat/', HTTP_X_TERRAFLOW_SECRET='fout', HTTP_X_TERRAFLOW_USER='x@terra.nl')
        self.assertEqual(fout.status_code, 403)
        self.assertEqual(self.client.get('/health/').status_code, 200)

    def test_engineer_ziet_alleen_eigen_aanvragen(self):
        self.vraag_aan('sem@terra.nl')
        self.vraag_aan('alex@terra.nl', omschrijving='Antenne')
        sem = self.staat('sem@terra.nl')
        self.assertEqual([r['omschrijving'] for r in sem['regels']], ['Servo'])
        self.assertFalse(sem['ik']['zietAlles'])
        self.assertNotIn('gebruikers', sem)
        self.assertNotIn('wagens', sem)
        self.assertEqual(len(self.staat('niek@terra.nl', admin=True)['regels']), 2)

    def test_engineer_kan_andermans_regel_niet_wijzigen_of_afvinken(self):
        rid = self.vraag_aan('sem@terra.nl')
        self.assertEqual(self.post(f'/api/regels/{rid}/', {'omschrijving': 'Gekaapt'}, 'alex@terra.nl').status_code, 404)
        Regel.objects.filter(pk=rid).update(status=Regel.BESTELD)
        self.post('/api/ontvangen/', {'ids': [rid]}, 'alex@terra.nl')
        self.assertEqual(Regel.objects.get(pk=rid).status, Regel.BESTELD)
        self.post('/api/ontvangen/', {'ids': [rid]}, 'sem@terra.nl')
        self.assertEqual(Regel.objects.get(pk=rid).status, Regel.ONTVANGEN)

    def test_rechten_per_actie(self):
        rid = self.vraag_aan('sem@terra.nl')
        self.assertEqual(self.post(f'/api/regels/{rid}/akkoord/', {}, 'sem@terra.nl').status_code, 403)
        self.assertEqual(self.post('/api/besteld/', {'winkel': 'mini-zshop.nl', 'ids': [rid]}, 'sem@terra.nl').status_code, 403)
        self.assertEqual(self.post('/api/team/', {'email': 'sem@terra.nl', 'goedkeuren': True}, 'sem@terra.nl').status_code, 403)
        self.assertEqual(self.post('/api/instellingen/', {'dagen': [0], 'ronde_uur': 14, 'vul_uur': 13}, 'sem@terra.nl').status_code, 403)
        # een besteller mag niet goedkeuren, ook niet via het wijzig-formulier
        self.staat('miranda@terra.nl')
        Gebruiker.objects.filter(email='miranda@terra.nl').update(mag_bestellen=True)
        self.assertEqual(self.post(f'/api/regels/{rid}/akkoord/', {}, 'miranda@terra.nl').status_code, 403)
        r = self.post(f'/api/regels/{rid}/', {'omschrijving': 'Servo', 'status': 'goedgekeurd'}, 'miranda@terra.nl')
        self.assertEqual(r.status_code, 403)

    def test_eigen_aanvraag_alleen_wijzigen_zolang_hij_wacht(self):
        rid = self.vraag_aan('sem@terra.nl')
        self.assertEqual(self.post(f'/api/regels/{rid}/', {'omschrijving': 'Servo v2', 'aantal': 3}, 'sem@terra.nl').status_code, 200)
        self.assertEqual(Regel.objects.get(pk=rid).aantal, 3)
        Regel.objects.filter(pk=rid).update(status=Regel.GOEDGEKEURD)
        self.assertEqual(self.post(f'/api/regels/{rid}/', {'omschrijving': 'Servo v3'}, 'sem@terra.nl').status_code, 403)


class Stroom(Basis):
    def test_van_aanvraag_tot_ontvangen(self):
        rid = self.vraag_aan('sem@terra.nl')
        regel = Regel.objects.get(pk=rid)
        self.assertEqual((regel.winkel, str(regel.prijs), regel.status), ('mini-zshop.nl', '12.50', 'aangevraagd'))
        self.push.assert_not_called()                     # geen spoed: komt in de gebundelde melding

        self.assertEqual(self.post(f'/api/regels/{rid}/akkoord/', {}, 'niek@terra.nl', admin=True).status_code, 200)
        self.staat('miranda@terra.nl')
        Gebruiker.objects.filter(email='miranda@terra.nl').update(mag_bestellen=True)
        r = self.post('/api/besteld/', {'winkel': 'mini-zshop.nl', 'ordernr': 'A-1', 'ids': [rid]}, 'miranda@terra.nl')
        self.assertEqual(r.status_code, 200, r.content)
        bestelling = Bestelling.objects.get()
        self.assertEqual((bestelling.ordernr, Regel.objects.get(pk=rid).status), ('A-1', 'besteld'))
        self.assertEqual(self.push.call_args.args[0], ['sem@terra.nl'])   # de aanvrager hoort dat het besteld is

        # twee keer dezelfde regels bestellen kan niet
        self.assertEqual(self.post('/api/besteld/', {'winkel': 'mini-zshop.nl', 'ids': [rid]}, 'miranda@terra.nl').status_code, 409)

    def test_volglink_alleen_van_bekende_vervoerder(self):
        rid = self.vraag_aan('sem@terra.nl')
        b = Bestelling.objects.create(winkel='mini-zshop.nl', ordernr='A-1')
        Regel.objects.filter(pk=rid).update(status=Regel.BESTELD, bestelling=b)
        pad = f'/api/bestellingen/{b.pk}/volglink/'
        for fout in ('https://mini-zshop.nl/mijn-account/orders/123?token=abc', 'https://evil.example/postnl.nl/track',
                     'http://jouw.postnl.nl/track-and-trace/3SABC', 'https://postnl.nl.evil.example/x', 'geen link'):
            r = self.post(pad, {'url': fout}, 'niek@terra.nl', admin=True)
            self.assertEqual(r.status_code, 400, fout)
        self.assertEqual(Bestelling.objects.get().tracking_url, '')
        self.push.reset_mock()
        goed = 'https://jouw.postnl.nl/track-and-trace/3SABC123-NL-4382ZA'
        self.assertEqual(self.post(pad, {'url': goed}, 'niek@terra.nl', admin=True).json()['vervoerder'], 'PostNL')
        self.assertEqual(self.push.call_args.args[0], ['sem@terra.nl'])
        self.assertEqual(self.post(pad, {'url': goed}, 'sem@terra.nl').status_code, 403)
        # de aanvrager ziet de volglink bij zijn eigen bestelling
        self.assertEqual(self.staat('sem@terra.nl')['bestellingen'][0]['tracking'], goed)

    def test_spoed_gaat_direct_naar_goedkeurders_en_daarna_bestellers(self):
        self.staat('niek@terra.nl', admin=True)
        self.staat('miranda@terra.nl')
        Gebruiker.objects.filter(email='miranda@terra.nl').update(mag_bestellen=True)
        rid = self.vraag_aan('sem@terra.nl', spoed=True)
        self.assertEqual(self.push.call_args.args[0], ['niek@terra.nl'])
        self.assertIn('Spoed', self.push.call_args.args[1])
        self.push.reset_mock()
        self.post(f'/api/regels/{rid}/akkoord/', {}, 'niek@terra.nl', admin=True)
        self.assertEqual(self.push.call_args.args[0], ['miranda@terra.nl'])

    def test_winkelwagen_melden_en_vultaak(self):
        self.staat('miranda@terra.nl')
        Gebruiker.objects.filter(email='miranda@terra.nl').update(mag_bestellen=True)
        rid = self.vraag_aan('sem@terra.nl', spoed=True)
        Regel.objects.filter(pk=rid).update(status=Regel.GOEDGEKEURD, goedgekeurd_op=timezone.now())
        taak = self.client.get('/api/vultaak/', **self.als('miranda@terra.nl')).json()
        self.assertTrue(taak['vullen'])                  # spoed wordt altijd meteen gevuld
        self.assertEqual(taak['regels'][0]['id'], rid)
        fout = self.post('/api/wagens/', {'winkel': 'mini-zshop.nl', 'url': 'https://evil.example/cart'}, 'miranda@terra.nl')
        self.assertEqual(fout.status_code, 400)
        ok = self.post('/api/wagens/', {'winkel': 'mini-zshop.nl', 'url': 'https://mini-zshop.nl/cart-2/',
                                        'regels': {str(rid): {'ok': True, 'notitie': ''}}}, 'miranda@terra.nl')
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(Regel.objects.get(pk=rid).wagen_ok)
        self.assertFalse(self.client.get('/api/vultaak/', **self.als('miranda@terra.nl')).json()['vullen'])
        self.assertEqual(self.client.get('/api/vultaak/', **self.als('sem@terra.nl')).status_code, 403)


class Tijd(Basis):
    def test_werkdagen(self):
        ma = lokaal(2026, 10, 5, 10)                                    # maandag 10:00
        self.assertEqual(logica.werkdagen_tussen(ma, lokaal(2026, 10, 7, 9)), 1)
        self.assertEqual(logica.werkdagen_tussen(ma, lokaal(2026, 10, 7, 10)), 2)
        vr = lokaal(2026, 10, 9, 15)                                    # vrijdag 15:00, weekend telt niet
        self.assertEqual(logica.werkdagen_tussen(vr, lokaal(2026, 10, 12, 16)), 1)
        self.assertEqual(logica.werkdagen_tussen(vr, lokaal(2026, 10, 13, 15)), 2)

    def test_ronde_gemist(self):
        momenten = {'dagen': [0, 2], 'ronde_uur': 14}
        self.assertEqual(logica.laatste_ronde(momenten, lokaal(2026, 10, 7, 16)), lokaal(2026, 10, 5, 14))   # woensdag 16:00: uitloop loopt nog
        ronde = logica.laatste_ronde(momenten, lokaal(2026, 10, 7, 17))
        self.assertEqual(ronde, lokaal(2026, 10, 7, 14))
        voor = Regel(status='goedgekeurd', goedgekeurd_op=lokaal(2026, 10, 7, 11))
        na = Regel(status='goedgekeurd', goedgekeurd_op=lokaal(2026, 10, 7, 15))
        self.assertTrue(logica.ronde_gemist(voor, ronde))
        self.assertFalse(logica.ronde_gemist(na, ronde))

    def test_periodieke_meldingen_gaan_een_keer(self):
        Gebruiker.objects.create(email='niek@terra.nl', is_admin=True)
        sem = Gebruiker.objects.create(email='sem@terra.nl')
        Regel.objects.create(aanvrager=sem, omschrijving='Oud', aangevraagd_op=lokaal(2026, 10, 1, 9))
        Regel.objects.create(aanvrager=sem, omschrijving='Nieuw', aangevraagd_op=lokaal(2026, 10, 6, 9))
        nu = lokaal(2026, 10, 6, 10)                                    # dinsdag 10:00
        self.assertEqual(meldingen.periodiek(nu), 2)                    # nieuwe aanvragen + wacht te lang
        titels = [c.args[1] for c in self.push.call_args_list]
        self.assertIn('2 nieuwe aanvragen op de kooplijst', titels)
        self.assertIn('1 aanvraag wacht al meer dan 2 werkdagen', titels)
        self.assertEqual(meldingen.periodiek(nu + timedelta(minutes=15)), 0)
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 6, 22)), 0)     # 's avonds niets
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 7, 9)), 1)      # volgende dag opnieuw: wacht nog steeds

    def test_mislukte_push_wordt_later_opnieuw_geprobeerd(self):
        Gebruiker.objects.create(email='niek@terra.nl', is_admin=True)
        Regel.objects.create(omschrijving='Nieuw', aangevraagd_op=lokaal(2026, 10, 6, 9))
        self.push.return_value = False
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 6, 10)), 0)
        self.assertEqual(MeldingLog.objects.count(), 0)
        self.push.return_value = True
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 6, 10, 15)), 1)

    def test_ronde_gemist_melding_naar_bestellers(self):
        Gebruiker.objects.create(email='miranda@terra.nl', mag_bestellen=True)
        Instelling.zet(Instelling.BESTELMOMENTEN, {'dagen': [0, 2], 'ronde_uur': 14, 'vul_uur': 13})
        Regel.objects.create(omschrijving='Kabel', status='goedgekeurd', goedgekeurd_op=lokaal(2026, 10, 5, 9), aangevraagd_op=lokaal(2026, 10, 5, 8))
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 5, 15)), 0)     # ronde loopt nog
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 5, 17, 5)), 1)
        self.assertEqual(self.push.call_args.args[0], ['miranda@terra.nl'])
        self.assertEqual(meldingen.periodiek(lokaal(2026, 10, 6, 9)), 0)      # niet nog eens voor dezelfde ronde


class Klein(TestCase):
    def test_prijs_en_winkel(self):
        for tekst, verwacht in (('€ 1.400,00', '1400.00'), ('18,39', '18.39'), ('€1,400.00', '1400.00'), ('€44.25', '44.25'), (12, '12.00')):
            self.assertEqual(str(logica.naar_prijs(tekst)), verwacht)
        self.assertIsNone(logica.naar_prijs(''))
        self.assertEqual(logica.winkel_van('https://eu.store.ui.com/eu/en/x'), 'ui.com')
        self.assertEqual(logica.winkel_van('https://nl.aliexpress.com/item/1.html'), 'aliexpress.com')
        self.assertEqual(logica.winkel_van('aliexpress.com/ssr/300'), 'aliexpress.com')
        self.assertEqual(logica.winkel_van('Quote opgevraagd'), '')
        self.assertEqual(logica.winkel_van('javascript:alert(1)'), '')


class Import(Basis):
    def _werkboek(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = f'{timezone.localdate().year} New Order Sheet'
        ws.append(['BESTELLINGEN WORDEN OP MAANDAG EN WOENSDAG GEDAAN'])
        ws.append(['Orderdate', 'Ordernr', 'Received', 'Invoice Number', 'Description of Goods', 'Quantity', 'No.in package',
                   'Total cost', 'Project Name', 'Remarks', 'Ordered by', 'Link'])
        gisteren = (timezone.localdate() - timedelta(days=1)).strftime('%d-%m-%Y')
        ws.append(['05-01-2026', '', '', 'IT1', 'Oud display', 2, 1, '€34.00', 'MODEC', '', 'Sem', 'https://www.texim-europe.com/x'])
        ws.append(['OK', '', '', '', 'Glasvezel kabel', 2, 1, '€24.00', 'Werkplaats', '10G', 'Jesse', 'https://eu.store.ui.com/eu/en/x'])
        ws.append(['', '', '', '', 'RP-SMA kabel', 4, 1, '€26.76', 'Modec', 'spoed', 'alex', 'https://www.allekabels.nl/x'])
        ws.append(['', '', '', '', 'Scherm', 1, 1, '€53.00', 'G3UT', '4-2 MC: geannuleerd', 'Jesse', 'https://www.ebay.co.uk/itm/1'])
        ws.append([gisteren, '129712', '', 'M45185', 'M2 moer', 100, 1, '€ 14,00', 'Werkplaats', '', 'Pepijn', 'https://www.rwproducts.nl/a'])
        ws.append([gisteren, '129712', '', 'M45185', 'M2,5 moer', 100, 1, '€ 12,00', 'Werkplaats', '', 'Pepijn', 'https://www.rwproducts.nl/b'])
        ws.append([gisteren, '555', gisteren, '', 'Al binnen', 1, 1, '€5.00', '', '', 'Niek', 'https://www.bol.com/x'])
        # zoals Google Sheets het opslaat: echte datumcel met dag en maand verwisseld, getallen als float
        g = timezone.localdate() - timedelta(days=1)
        if g.day <= 12:
            ws.append([datetime(g.year, g.day, g.month), 3020726962.0, None, None, 'Tiewraps', 1.0, 1000.0, 26.8, None, None, 'Jesse',
                       'https://nl.rs-online.com/web/p/cable-ties/2132995'])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def test_alleen_wat_openstaat_komt_mee(self):
        proef = importeer_xlsx(self._werkboek(), proef=True)
        self.assertEqual(Regel.objects.count(), 0)
        extra = 1 if (timezone.localdate() - timedelta(days=1)).day <= 12 else 0
        self.assertEqual(proef['geteld'], {'aangevraagd': 1, 'goedgekeurd': 1, 'besteld': 2 + extra, 'overgeslagen': 3, 'dubbel': 0})
        importeer_xlsx(self._werkboek())
        self.assertEqual(Regel.objects.count(), 4 + extra)
        self.assertEqual(Bestelling.objects.count(), 1 + extra)         # twee regels van één order horen bij elkaar
        if extra:
            tiewraps = Regel.objects.get(omschrijving='Tiewraps')
            self.assertEqual((tiewraps.bestelling.ordernr, str(tiewraps.prijs), tiewraps.per_verpakking), ('3020726962', '26.80', 1000))
        kabel = Regel.objects.get(omschrijving='RP-SMA kabel')
        self.assertEqual((kabel.status, kabel.spoed, kabel.aanvrager_naam, kabel.winkel), ('aangevraagd', True, 'Alex', 'allekabels.nl'))
        self.assertEqual(str(Regel.objects.get(omschrijving='M2 moer').prijs), '14.00')
        nog_eens = importeer_xlsx(self._werkboek())
        self.assertEqual((nog_eens['geteld']['dubbel'], Regel.objects.count()), (4 + extra, 4 + extra))

    def test_verwisselde_datum(self):
        from .importeren import _datum
        vandaag = datetime(2026, 10, 7).date()
        self.assertEqual(_datum(datetime(2026, 6, 10), vandaag), datetime(2026, 10, 6).date())    # getypt als 06-10-2026
        self.assertEqual(_datum(datetime(2026, 12, 10), vandaag), datetime(2026, 12, 10).date())   # 12 oktober ligt nog in de toekomst
        self.assertEqual(_datum(datetime(2026, 9, 29), vandaag), datetime(2026, 9, 29).date())    # 29 kan geen maand zijn
        self.assertEqual(_datum('29-09-2026'), datetime(2026, 9, 29).date())
        self.assertIsNone(_datum('0-10-2026'))
        self.assertIsNone(_datum('OK'))

    def test_naam_koppelen_geeft_engineer_zijn_regels(self):
        importeer_xlsx(self._werkboek())
        alex = self.staat('alex@terra.nl')
        self.assertEqual(alex['regels'], [])                            # niet automatisch op naam gekoppeld
        niek = self.staat('niek@terra.nl', admin=True)
        self.assertIn('Alex', niek['losseNamen'])
        r = self.post('/api/koppel/', {'naam': 'Alex', 'id': alex['ik']['id']}, 'niek@terra.nl', admin=True)
        self.assertEqual(r.json()['aantal'], 1)
        self.assertEqual([x['omschrijving'] for x in self.staat('alex@terra.nl')['regels']], ['RP-SMA kabel'])
