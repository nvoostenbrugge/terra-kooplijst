"""Kooplijst-koppeling: doorgeefpagina /kooplijst/ (login, headers, CSRF) en de push-ingang voor de dienst."""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from quotes.models import TeamRole


class _Antwoord:
    def __init__(self, status=200, content=b'{"ok": true}', headers=None):
        self.status_code, self.content = status, content
        self.headers = headers or {'Content-Type': 'application/json'}


@override_settings(KOOPLIJST_SECRET='geheim-123', KOOPLIJST_UPSTREAM='http://127.0.0.1:8091')
class KooplijstTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.admin = U.objects.create_user(username='kla', password='x', email='KLA@example.com', first_name='Niek', last_name='Test')
        TeamRole.objects.create(user=self.admin, role='account_manager', is_super_admin=True)
        self.user = U.objects.create_user(username='klu', password='x', email='klu@example.com')
        TeamRole.objects.create(user=self.user, role='operations')

    def test_login_verplicht(self):
        r = Client().get('/kooplijst/', HTTP_HOST='localhost')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_headers_komen_van_terraflow_en_niet_van_de_browser(self):
        c = Client(); c.force_login(self.user)
        with mock.patch('quotes.kooplijst_views.requests.request', return_value=_Antwoord()) as req:
            r = c.get('/kooplijst/api/staat/?x=1', HTTP_HOST='localhost',
                      HTTP_X_TERRAFLOW_USER='iemand@anders.nl', HTTP_X_TERRAFLOW_ADMIN='1', HTTP_X_TERRAFLOW_SECRET='gok')
        self.assertEqual(r.status_code, 200)
        args, kwargs = req.call_args
        self.assertEqual(args, ('GET', 'http://127.0.0.1:8091/api/staat/?x=1'))
        h = kwargs['headers']
        self.assertEqual((h['X-TerraFlow-User'], h['X-TerraFlow-Admin'], h['X-TerraFlow-Secret']), ('klu@example.com', '0', 'geheim-123'))
        c.force_login(self.admin)
        with mock.patch('quotes.kooplijst_views.requests.request', return_value=_Antwoord()) as req:
            c.get('/kooplijst/', HTTP_HOST='localhost')
        h = req.call_args.kwargs['headers']
        self.assertEqual((h['X-TerraFlow-User'], h['X-TerraFlow-Admin'], h['X-TerraFlow-Name']), ('kla@example.com', '1', 'Niek Test'))

    def test_post_vraagt_csrf_token(self):
        c = Client(enforce_csrf_checks=True); c.force_login(self.user)
        with mock.patch('quotes.kooplijst_views.requests.request', return_value=_Antwoord()) as req:
            zonder = c.post('/kooplijst/api/regels/', '{}', content_type='application/json', HTTP_HOST='localhost')
            self.assertEqual(zonder.status_code, 403)
            req.assert_not_called()
            c.get('/kooplijst/', HTTP_HOST='localhost')                     # zet het csrftoken-cookie
            token = c.cookies['csrftoken'].value
            met = c.post('/kooplijst/api/regels/', '{"omschrijving": "x"}', content_type='application/json',
                         HTTP_HOST='localhost', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(met.status_code, 200)
        self.assertEqual(req.call_args.kwargs['data'], b'{"omschrijving": "x"}')

    def test_dienst_onbereikbaar_geeft_nette_melding(self):
        import requests
        c = Client(); c.force_login(self.user)
        with mock.patch('quotes.kooplijst_views.requests.request', side_effect=requests.ConnectionError('dicht')):
            self.assertEqual(c.get('/kooplijst/', HTTP_HOST='localhost').status_code, 502)
            api = c.get('/kooplijst/api/staat/', HTTP_HOST='localhost')
        self.assertEqual(api.status_code, 502)
        self.assertIn('fout', api.json())

    @override_settings(KOOPLIJST_SECRET='')
    def test_niet_geinstalleerd(self):
        c = Client(); c.force_login(self.user)
        self.assertEqual(c.get('/kooplijst/', HTTP_HOST='localhost').status_code, 404)
        r = Client().post('/api/internal/kooplijst/push/', '{}', content_type='application/json', HTTP_HOST='localhost')
        self.assertEqual(r.status_code, 403)

    def test_knop_alleen_als_geinstalleerd(self):
        import inspect
        from quotes.services.project_helpers import get_user_allowed_views
        if 'kooplijst' not in inspect.getsource(get_user_allowed_views):
            self.skipTest('de knop staat niet in get_user_allowed_views (koppeling zonder knop geïnstalleerd)')
        self.assertIn('kooplijst', [v['id'] for v in get_user_allowed_views(self.user)])
        with override_settings(KOOPLIJST_SECRET=''):
            self.assertNotIn('kooplijst', [v['id'] for v in get_user_allowed_views(self.user)])

    def test_push_alleen_met_geheim(self):
        body = json.dumps({'emails': ['klu@example.com', 'Kla@Example.com', 'onbekend@example.com'], 'title': 'Spoed', 'body': 'x',
                           'url': 'https://evil.example/', 'tag': 'kl'})
        c = Client()
        zonder = c.post('/api/internal/kooplijst/push/', body, content_type='application/json', HTTP_HOST='localhost')
        fout = c.post('/api/internal/kooplijst/push/', body, content_type='application/json', HTTP_HOST='localhost',
                      HTTP_X_KOOPLIJST_SECRET='fout')
        self.assertEqual((zonder.status_code, fout.status_code), (403, 403))
        with mock.patch('quotes.services.push_helpers.send_push_to_users',
                        return_value={'users_reached': 2, 'devices_sent': 2, 'failed': 0}) as send:
            ok = c.post('/api/internal/kooplijst/push/', body, content_type='application/json', HTTP_HOST='localhost',
                        HTTP_X_KOOPLIJST_SECRET='geheim-123')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()['users_found'], 2)
        users = send.call_args.args[0]
        self.assertEqual(sorted(u.username for u in users), ['kla', 'klu'])
        self.assertEqual(send.call_args.kwargs['url'], '/kooplijst/')     # nooit een link naar buiten
