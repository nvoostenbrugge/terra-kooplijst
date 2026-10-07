"""
Terra Kooplijst: losse dienst naast TerraFlow.

De app heeft geen eigen login. TerraFlow zet hem achter de gewone login op /kooplijst/ en geeft
bij elk verzoek mee wie er kijkt (zie inkoop/toegang.py). Daarom luistert de dienst alleen op
localhost en weigert hij elk verzoek zonder het gedeelde geheim.
"""
from pathlib import Path

from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='alleen-voor-ontwikkeling')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']

TERRAFLOW_SECRET = config('TERRAFLOW_SECRET', default='')
TERRAFLOW_URL = config('TERRAFLOW_URL', default='http://127.0.0.1:8000').rstrip('/')
DEV_USER = config('DEV_USER', default='') if DEBUG else ''
DEV_ADMIN = config('DEV_ADMIN', default=False, cast=bool) if DEBUG else False

VERSION = (BASE_DIR / 'VERSION').read_text().strip() if (BASE_DIR / 'VERSION').exists() else '0'

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'inkoop',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    # Geen CsrfViewMiddleware: de CSRF-controle gebeurt in TerraFlow, vóór het verzoek hier aankomt.
    'inkoop.toegang.TerraFlowToegang',
]

ROOT_URLCONF = 'kooplijst_site.urls'
WSGI_APPLICATION = 'kooplijst_site.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': []},
}]

if config('DB_USER', default=''):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='terra_kooplijst'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': 60,
    }}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LANGUAGE_CODE = 'nl'
TIME_ZONE = 'Europe/Amsterdam'
USE_I18N = False
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'kort': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'kort'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}

# Vervoerders waarvan een volglink gedeeld mag worden. Alles daarbuiten wordt geweigerd,
# zodat er nooit per ongeluk een inlog- of accountlink bij een engineer terechtkomt.
VERVOERDER_DOMEINEN = {
    'postnl.nl': 'PostNL', 'postnl.com': 'PostNL',
    'dhl.com': 'DHL', 'dhl.nl': 'DHL', 'dhl.de': 'DHL', 'dhlparcel.nl': 'DHL', 'dhlecommerce.nl': 'DHL',
    'dpd.nl': 'DPD', 'dpd.com': 'DPD', 'dpd.de': 'DPD', 'dpdgroup.com': 'DPD',
    'ups.com': 'UPS',
    'gls-info.nl': 'GLS', 'gls-group.eu': 'GLS', 'gls-group.com': 'GLS', 'gls-pakete.de': 'GLS',
    'fedex.com': 'FedEx', 'tnt.com': 'TNT',
    'budbee.com': 'Budbee', 'trunkrs.nl': 'Trunkrs',
    '17track.net': '17TRACK',
}
