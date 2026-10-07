"""Reempaquetar únicamente una demo generada, excluyendo sus datos de verificación."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(); parser.add_argument('--bundle', required=True); parser.add_argument('--output', required=True)
args = parser.parse_args(); bundle = Path(args.bundle).resolve(); output = Path(args.output).resolve()
if not bundle.is_relative_to(ROOT / 'work') or bundle.name != 'ControlEmpresaDemo': raise RuntimeError('Se requiere una carpeta de demo generada dentro de work.')
for name in ('demo_launcher.py', 'test_demo_bundle.py', 'build_demo.py'):
    shutil.copy2(ROOT / 'tools' / name, bundle / 'app' / 'tools' / name)
for name in ('login.html', 'base.html'): shutil.copy2(ROOT / 'templates' / name, bundle / 'app' / 'templates' / name)
shutil.copy2(ROOT / '.venv' / 'Lib' / 'site-packages' / 'certifi' / 'cacert.pem', bundle / 'runtime' / 'python' / 'Lib' / 'site-packages' / 'certifi' / 'cacert.pem')
temporary = output.with_suffix('.partial.zip')
with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in bundle.rglob('*'):
        if not path.is_file(): continue
        relative = path.relative_to(bundle)
        if relative.parts[0] == 'data' or '__pycache__' in relative.parts or path.suffix in ('.pyc', '.log'): continue
        if path.name in ('config.local.json', 'sunat.local.json', 'demo-state.json') or path.suffix in ('.pfx', '.p12', '.backup'): raise RuntimeError('Archivo privado detectado.')
        if path.suffix == '.pem' and relative.as_posix() != 'runtime/python/Lib/site-packages/certifi/cacert.pem': raise RuntimeError('Certificado no permitido.')
        archive.write(path, Path(bundle.name) / relative)
with zipfile.ZipFile(temporary) as archive:
    names = archive.namelist()
    if any(name.startswith('ControlEmpresaDemo/data/') for name in names): raise RuntimeError('La entrega incluye datos de prueba.')
    if archive.testzip(): raise RuntimeError('ZIP incompleto.')
temporary.replace(output)
digest = hashlib.sha256()
with output.open('rb') as stream:
    for part in iter(lambda: stream.read(1024 * 1024), b''): digest.update(part)
metadata = {'file': output.name, 'size': output.stat().st_size, 'sha256': digest.hexdigest(), 'platform': 'Windows x64',
    'checked': 'Runtime copiado, PostgreSQL aislado, migraciones, datos ficticios, acceso, seis pantallas y firma beta. Sin envío de datos del negocio.'}
output.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
print('Demo final verificada: ' + str(round(output.stat().st_size / 1024**2, 1)) + ' MB. Sin data ni credenciales privadas.')
