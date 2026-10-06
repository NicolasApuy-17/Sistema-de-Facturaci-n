import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
name = os.environ['FACT_ADMIN_NAME']
if User.objects.filter(username=name).exists():
    raise RuntimeError('El usuario ya existe. No se cambió su contraseña.')
User.objects.create_user(username=name, password=os.environ['FACT_ADMIN_PASSWORD'], is_staff=True)
print('Administrador creado.')
