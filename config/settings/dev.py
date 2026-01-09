from .base import *

# Entwicklungseinstellungen: permissive Hosts und lokale CSRF-Origin.
DEBUG = True

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["*"]

if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = ["http://localhost:8000"]

