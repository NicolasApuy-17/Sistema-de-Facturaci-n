"""Arranque, login y persistencia sobre el runtime copiado; sin abrir ventanas."""
import json
from pathlib import Path
import sys
import time
import urllib.request
from types import SimpleNamespace

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
import demo_launcher

def test():
    data = demo_launcher.DATA; data.mkdir(exist_ok=True)
    state_file = data / 'demo-state.json'
    import secrets
    if state_file.exists(): state = json.loads(state_file.read_text(encoding='utf-8'))
    else:
        state = {'pg_port': 55439, 'web_port': 18765, 'secret': secrets.token_urlsafe(64), 'owner_password': secrets.token_urlsafe(40), 'app_password': secrets.token_urlsafe(40)}
        state_file.write_text(json.dumps(state), encoding='utf-8'); demo_launcher.private_file(state_file)
    demo = object.__new__(demo_launcher.Demo)
    demo.state, demo.server, demo.pg_started = state, None, False
    demo.root = SimpleNamespace(after=lambda delay, callback: callback())
    demo.ready = lambda: None
    def failed(error): raise RuntimeError(error)
    demo.failed = failed
    try:
        import tkinter
        assert Path(tkinter.Tcl().eval('info library')).resolve().is_relative_to(demo_launcher.BUNDLE / 'runtime' / 'python')
        demo.prepare()
        with urllib.request.urlopen(f'http://127.0.0.1:{state["web_port"]}/ingresar/', timeout=10) as response:
            assert response.status == 200
            assert b'csrfmiddlewaretoken' in response.read()
        import django
        from django.test import Client
        from core.models import BetaSubmission, Company, Document, Product
        from django.contrib.auth import get_user_model
        from django.conf import settings
        self_client = Client(HTTP_HOST='127.0.0.1')
        assert self_client.login(username='demo', password='PruebaEmpresa-2026!')
        assert get_user_model().objects.get(username='demo').is_staff
        assert settings.DATABASES['default']['NAME'] == 'facturacion_demo'
        assert settings.DATABASES['default']['USER'] == 'demo_app'
        assert Product.objects.count() == 3 and Document.objects.count() == 2
        assert Company.objects.get().name == 'EMPRESA FICTICIA PARA DEMOSTRACION'
        assert BetaSubmission.objects.count() == 0
        for path in ['/', '/inventario/', '/clientes/', '/comprobantes/', '/guias/', '/configuracion/']:
            response = self_client.get(path)
            assert response.status_code == 200, path
            assert 'DEMOSTRACIÓN'.encode() in response.content
        draft = Document.objects.get(status='BORRADOR')
        response = self_client.post(f'/comprobantes/{draft.pk}/beta/preparar/')
        assert response.status_code == 302
        assert BetaSubmission.objects.count() == 1
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper, rolcreatedb FROM pg_roles WHERE rolname=current_user')
            assert cursor.fetchone() == (False, False)
        print('Runtime portable, PostgreSQL independiente, migraciones, datos ficticios, login, seis pantallas y firma beta: OK.')
        print('No se conectó a la base del negocio ni se envió a SUNAT.')
    finally:
        if demo.server: demo.server.close(); demo.server.task_dispatcher.shutdown(timeout=3)
        from django.db import connections
        connections.close_all()
        if demo.pg_started:
            demo_launcher.command([demo_launcher.PG / 'pg_ctl.exe', '-D', data / 'postgres', '-m', 'fast', '-w', 'stop'])

if __name__ == '__main__': test()
