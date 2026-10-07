"""Pruebas PostgreSQL aisladas. No toca bases de desarrollo o producción."""
import os
import secrets
import subprocess
import sys
import tempfile
import importlib.util
import json
import shutil
from pathlib import Path
import psycopg

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(os.environ.get('POSTGRES_BIN', r'C:\Program Files\PostgreSQL\18\bin'))
work = ROOT / 'work'
work.mkdir(exist_ok=True)
folder = Path(tempfile.mkdtemp(prefix='pg-check-', dir=work))
password = secrets.token_urlsafe(40)
pwfile = folder / 'password.txt'
pwfile.write_text(password, encoding='ascii')
data = folder / 'data'
env = os.environ.copy()
env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1', FACTURACION_TEST='1', DJANGO_SECRET_KEY=secrets.token_urlsafe(64), PGHOST='127.0.0.1',
           PGPORT='55432', PGDATABASE='facturacion_checks', PGUSER='checks_owner', PGPASSWORD=password)
def command(args, **kwargs):
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', **kwargs)
    if result.returncode:
        print(result.stdout[-5000:])
        print(result.stderr[-5000:])
        raise RuntimeError('Falló una comprobación; revisa el diagnóstico anterior.')
    return result
started = False
try:
    command([str(BIN / 'initdb.exe'), '-D', str(data), '-U', 'checks_owner', '-A', 'scram-sha-256',
             '--pwfile', str(pwfile), '--encoding=UTF8', '--locale=C'])
    pwfile.unlink()
    # En Windows los procesos del servidor pueden heredar pipes: usar DEVNULL evita bloquear communicate().
    subprocess.run([str(BIN / 'pg_ctl.exe'), '-D', str(data), '-l', str(folder / 'postgres.log'),
                    '-o', '-h 127.0.0.1 -p 55432', '-w', 'start'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=70)
    started = True
    with psycopg.connect(host='127.0.0.1', port=55432, dbname='postgres', user='checks_owner', password=password, autocommit=True) as conn:
        conn.execute('CREATE DATABASE facturacion_checks')
    command([sys.executable, 'manage.py', 'makemigrations', 'core', '--noinput'])
    command([sys.executable, 'manage.py', 'migrate', '--noinput'])
    command([sys.executable, 'manage.py', 'collectstatic', '--noinput'])
    command([sys.executable, 'manage.py', 'check'])
    labels = sys.argv[1:] or ['core']
    result = command([sys.executable, 'manage.py', 'test', *labels, '--noinput', '--verbosity=2'])
    print(result.stdout)
    print(result.stderr)
    # Verificar el asistente real en una copia aislada, incluida la separación de roles.
    preview_root = folder / 'installation'
    preview_root.mkdir()
    for directory in ['config', 'core', 'templates', 'static', 'tools']:
        shutil.copytree(ROOT / directory, preview_root / directory, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT / 'manage.py', preview_root / 'manage.py')
    with psycopg.connect(host='127.0.0.1', port=55432, dbname='postgres', user='checks_owner', password=password, autocommit=True) as conn:
        conn.execute('CREATE ROLE facturacion_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
        from psycopg import sql
        conn.execute(sql.SQL('CREATE ROLE postgres LOGIN SUPERUSER PASSWORD {}').format(sql.Literal(password)))
        conn.execute('CREATE DATABASE facturacion_dev OWNER facturacion_admin')
    spec = importlib.util.spec_from_file_location('configure_test', ROOT / 'tools' / 'configure.py')
    wizard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wizard)
    wizard.ROOT = preview_root
    wizard.prepare({'database': 'facturacion_dev', 'port': 55432, 'postgres_password': password,
                    'username': 'administrador_prueba', 'password': 'Vista-local-prueba-9472!'})
    config = json.loads((preview_root / 'config.local.json').read_text(encoding='utf-8'))
    db = config['database']
    with psycopg.connect(host=db['host'], port=db['port'], dbname=db['name'], user=db['user'], password=db['password'], autocommit=True) as conn:
        assert conn.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone() == (False, False, False)
        assert conn.execute('SELECT is_staff FROM auth_user WHERE username=%s', ('administrador_prueba',)).fetchone() == (True,)
        assert conn.execute("SELECT tableowner FROM pg_tables WHERE tablename='core_customer'").fetchone() == ('facturacion_admin',)
        try: conn.execute('CREATE TABLE public.forbidden_table (id integer)')
        except psycopg.errors.InsufficientPrivilege: pass
        else: raise AssertionError('El usuario de aplicación tiene permisos de crear tablas.')
    print('Asistente de instalación y permisos limitados: OK. La base real no fue modificada.')
    # Respaldo y restauración reales en un destino nuevo dentro del clúster temporal.
    backup_spec = importlib.util.spec_from_file_location('backup_test', ROOT / 'tools' / 'backup.py')
    backup_tool = importlib.util.module_from_spec(backup_spec)
    backup_spec.loader.exec_module(backup_tool)
    backup_path = backup_tool.create_backup(config, folder / 'backups')
    backup_tool.verify_backup(backup_path)
    recovered_name = 'facturacion_recuperada_20261006000000'
    counts = backup_tool.restore_new_database(backup_path, config, password, recovered_name)
    assert counts['auth_user'] == 1
    with psycopg.connect(host='127.0.0.1', port=55432, dbname=recovered_name, user='checks_owner', password=password) as conn:
        assert conn.execute('SELECT username, is_staff FROM auth_user').fetchone() == ('administrador_prueba', True)
        assert conn.execute("SELECT tableowner FROM pg_tables WHERE tablename='core_product'").fetchone() == ('facturacion_admin',)
    try: backup_tool.restore_new_database(backup_path, config, password, recovered_name)
    except ValueError: pass
    else: raise AssertionError('La restauración permite sobrescribir una base existente.')
    original_bytes = backup_path.read_bytes()
    backup_path.write_bytes(original_bytes + b'alteracion')
    try: backup_tool.verify_backup(backup_path)
    except ValueError: pass
    else: raise AssertionError('No se detectó un respaldo alterado.')
    backup_path.write_bytes(original_bytes)
    with psycopg.connect(host='127.0.0.1', port=55432, dbname=db['name'], user=db['user'], password=db['password'], autocommit=True) as conn:
        try: conn.execute('DELETE FROM core_auditevent')
        except psycopg.errors.InsufficientPrivilege: pass
        else: raise AssertionError('La aplicación permite eliminar la auditoría.')
    print('Respaldo, restauración en base nueva, integridad y auditoría protegida: OK.')
finally:
    if pwfile.exists(): pwfile.unlink()
    if started:
        result = subprocess.run([str(BIN / 'pg_ctl.exe'), '-D', str(data), '-m', 'fast', '-w', 'stop'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=70)
        if result.returncode: print('Atención: no se pudo detener el clúster aislado de pruebas.')
