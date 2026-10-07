"""Gunicorn voor de kooplijst: alleen op localhost, TerraFlow zet de dienst achter de login op /kooplijst/."""
import os

from decouple import config as _env   # niet "config" noemen: zo heet ook een instelling van gunicorn zelf

bind = f"127.0.0.1:{_env('PORT', default='8091')}"
workers = 2
threads = 4
timeout = 60
accesslog = None
errorlog = '-'
chdir = os.path.dirname(os.path.abspath(__file__))
