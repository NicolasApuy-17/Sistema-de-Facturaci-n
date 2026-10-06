import json
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if not (ROOT / 'config.local.json').exists():
    raise SystemExit('Primero abre Configurar.cmd.')
config = json.loads((ROOT / 'config.local.json').read_text(encoding='utf-8'))
port = config.get('port', 8765)
url = f'http://127.0.0.1:{port}'
from config.wsgi import application
from django.db import connection
try:
    connection.ensure_connection()
except Exception:
    raise SystemExit('No se pudo conectar con PostgreSQL. Comprueba que el servicio esté activo y que el asistente haya terminado.')
connection.close()
probe = socket.socket()
try:
    probe.bind(('127.0.0.1', port))
except OSError:
    raise SystemExit(f'El puerto {port} ya está ocupado. Si el sistema ya está abierto, utiliza su ventana existente.')
finally:
    probe.close()
def open_browser():
    time.sleep(1.5)
    webbrowser.open(url)
threading.Thread(target=open_browser, daemon=True).start()
print(f'Control Empresa disponible en {url}')
print('Mantén esta ventana abierta mientras utilizas el sistema. Para cerrar: Ctrl+C.')
from waitress import serve
serve(application, host='127.0.0.1', port=port, threads=6)
