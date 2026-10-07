"""Demo portable: conexión exclusiva a su clúster, sin configuración de la empresa."""
import os
from .settings import *

DEMO_MODE = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
SECRET_KEY = os.environ['DEMO_SECRET_KEY']
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'facturacion_demo',
    'HOST': '127.0.0.1', 'PORT': os.environ['DEMO_PG_PORT'], 'USER': os.environ['DEMO_PG_USER'],
    'PASSWORD': os.environ['DEMO_PG_PASSWORD'], 'CONN_MAX_AGE': 60}}
