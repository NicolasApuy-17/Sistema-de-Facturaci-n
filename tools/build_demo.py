"""Paquete portable con lista explícita de código y runtimes; excluye datos reales."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
output = Path(args.output).resolve()
if output.exists(): raise RuntimeError('El archivo de entrega ya existe. Usa otro nombre para conservarlo.')
folder = ROOT / 'work' / ('demo-build-' + datetime.now().strftime('%Y%m%d-%H%M%S')) / 'ControlEmpresaDemo'
app = folder / 'app'; app.mkdir(parents=True)
ignore = shutil.ignore_patterns('__pycache__', '*.pyc', 'config.local.json', 'sunat.local.json', '*.pfx', '*.p12', '*.pem', '*.log')
for name in ('config', 'core', 'templates', 'static', 'tools'):
    shutil.copytree(ROOT / name, app / name, ignore=ignore)
for name in ('manage.py', 'requirements.txt', 'README.md'): shutil.copy2(ROOT / name, app / name)
base_python = Path(sys.base_prefix)
target_python = folder / 'runtime' / 'python'; target_python.mkdir(parents=True)
for name in ('python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
    shutil.copy2(base_python / name, target_python / name)
for name in ('DLLs', 'tcl'):
    shutil.copytree(base_python / name, target_python / name, ignore=ignore)
shutil.copytree(base_python / 'Lib', target_python / 'Lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc', 'test', 'tests', 'idlelib', 'ensurepip', 'venv'))
shutil.copytree(ROOT / '.venv' / 'Lib' / 'site-packages', target_python / 'Lib' / 'site-packages', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
postgres = Path(r'C:\Program Files\PostgreSQL\18')
for name in ('bin', 'lib', 'share'):
    shutil.copytree(postgres / name, folder / 'runtime' / 'postgres' / name, ignore=ignore)
for name in ('server_license.txt', 'commandlinetools_3rd_party_licenses.txt'):
    shutil.copy2(postgres / name, folder / 'runtime' / 'postgres' / name)
(folder / 'Iniciar demo.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0runtime\\python\\pythonw.exe" "%~dp0app\\tools\\demo_launcher.py"\r\n', encoding='ascii')
instructions = '''CONTROL EMPRESA — DEMOSTRACION PARA WINDOWS DE 64 BITS

1. Extrae TODO el ZIP con “Extraer todo”. No abras la demo dentro del ZIP.
2. Guarda la carpeta, por ejemplo, en Documentos. Evita carpetas sincronizadas mientras está abierta.
3. Abre Iniciar demo.cmd con doble clic. La primera apertura puede tomar unos minutos.
4. Se abrirá el navegador. Usuario: demo. Contraseña: PruebaEmpresa-2026!
5. Mantén abierta la ventana “Control Empresa · Demostración”. Para terminar, pulsa Cerrar demostración.

No requiere instalar Python o PostgreSQL ni abrir Visual Studio. No ejecutes como administrador.
No instala servicios de Windows ni modifica otra instalación de PostgreSQL.
Solo escucha en tu computadora. Las operaciones internas no requieren internet.
Las pruebas se conservan en la subcarpeta data. No borres ni muevas esa carpeta mientras la demo esté abierta.
Esta es una copia de prueba con datos ficticios. No registres ventas reales ni introduzcas certificados propios.
Los documentos internos no tienen validez tributaria. Una aceptación en SUNAT beta tampoco emite una factura real.
La empresa ficticia usa el RUC público de los ejemplos del manual SUNAT, únicamente para pruebas beta.
El envío opcional a SUNAT beta requiere internet y una confirmación en pantalla. No ingreses Clave SOL.
Las credenciales demo son públicas: esta copia no es la instalación de producción.

PRUEBAS SUGERIDAS
- Inventario: edita un producto y registra una entrada o salida. Comprueba el stock.
- Clientes: agrega un cliente ficticio.
- Facturas/boletas: crea una venta, registra la operación interna y un pago parcial.
- Estado de cuenta: comprueba el saldo del cliente ficticio con RUC; incluye una venta y un pago de ejemplo.
- Notas: crea una devolución por ítem referida a la venta de ejemplo; confirma mercadería recibida y revisa stock y saldo.
- Guías: crea borradores remitente y transportista, y revisa los productos trasladados.
- Impresión: abre Imprimir / guardar PDF.
- XML: descarga un XML de prueba; opcionalmente prepara la factura beta y revisa sus archivos antes de enviar.

ANOTA TU OPINION
Qué tarea probaste, qué esperabas, qué pasó y qué parte resultó confusa.
Si aparece un error, anota la pantalla, la acción y el mensaje.
No envíes la subcarpeta data ni contraseñas: para reportar basta describir el problema.

La demo se probó en la computadora de desarrollo. También debe comprobarse en el equipo de destino.
Si Windows o el antivirus bloquean la apertura, consulta a quien administra esa computadora; no desactives sus protecciones.
'''
(folder / 'LEEME - COMO PROBAR.txt').write_text(instructions, encoding='utf-8-sig')
env = dict(__import__('os').environ)
env.update(DJANGO_SETTINGS_MODULE='config.demo_settings', DJANGO_SECRET_KEY='collectstatic-demo-no-real-secrets', DEMO_SECRET_KEY='collectstatic-demo-no-real-secrets', DEMO_PG_PORT='55439', DEMO_PG_USER='demo_app', DEMO_PG_PASSWORD='not-used-for-build')
subprocess.run([str(target_python / 'python.exe'), str(app / 'manage.py'), 'collectstatic', '--noinput'], cwd=app, env=env, check=True, capture_output=True)
for forbidden in ('config.local.json', 'sunat.local.json', '*.pfx', '*.p12', '*.backup', 'demo-state.json'):
    if list(folder.rglob(forbidden)): raise RuntimeError('Se encontró un archivo privado o de datos en la entrega.')
allowed_public_pem = target_python / 'Lib' / 'site-packages' / 'certifi' / 'cacert.pem'
if any(path != allowed_public_pem for path in folder.rglob('*.pem')): raise RuntimeError('Certificado no permitido en la entrega.')
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in folder.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts: archive.write(path, path.relative_to(folder.parent))
manifest = {'file': output.name, 'size': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'platform': 'Windows x64', 'content': 'Código, Python, PostgreSQL, licencias y guía. Sin datos ni credenciales reales.'}
output.with_suffix('.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps({'archive': str(output), 'size_mb': round(output.stat().st_size / 1024**2, 1), 'build_folder': str(folder)}, ensure_ascii=False))
