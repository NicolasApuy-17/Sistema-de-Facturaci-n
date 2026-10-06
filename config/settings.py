import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
path = BASE_DIR / 'config.local.json'
LOCAL = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
TESTING = os.environ.get('FACTURACION_TEST') == '1'
SECRET_KEY = LOCAL.get('secret_key') or os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('Primero ejecuta Configurar.cmd para preparar la conexión local.')
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost'] + LOCAL.get('allowed_hosts', [])
if TESTING:
    ALLOWED_HOSTS += ['testserver']
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
                  'django.contrib.messages', 'django.contrib.staticfiles', 'core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
              'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
              'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
              'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware', 'core.middleware.LoginThrottle']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages', 'core.context.brand']}}]
WSGI_APPLICATION = 'config.wsgi.application'
db = LOCAL.get('database', {})
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ.get('PGDATABASE', db.get('name', 'facturacion_dev')),
    'USER': os.environ.get('PGUSER', db.get('user', 'facturacion_app')),
    'PASSWORD': os.environ.get('PGPASSWORD', db.get('password', '')),
    'HOST': os.environ.get('PGHOST', db.get('host', '127.0.0.1')),
    'PORT': os.environ.get('PGPORT', str(db.get('port', 5432))), 'CONN_MAX_AGE': 60}}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'es-pe'
TIME_ZONE = 'America/Lima'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/ingresar/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/ingresar/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 28800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
