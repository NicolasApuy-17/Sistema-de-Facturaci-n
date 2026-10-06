"""Copias PostgreSQL sin incluir credenciales de conexión."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(os.environ.get('POSTGRES_BIN', r'C:\Program Files\PostgreSQL\18\bin'))
LOCK = threading.Lock()

def read_config(root=ROOT): return json.loads((root / 'config.local.json').read_text(encoding='utf-8'))

def db_env(config):
    env = os.environ.copy()
    for key in ['PGOPTIONS', 'PGUSER', 'PGDATABASE', 'PGHOST', 'PGPORT', 'PGPASSWORD']: env.pop(key, None)
    db = config['database']
    env.update(PGHOST=db['host'], PGPORT=str(db['port']), PGUSER=db['user'], PGDATABASE=db['name'], PGPASSWORD=db['password'])
    return env

def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): sha.update(block)
    return sha.hexdigest()

def run(args, env):
    result = subprocess.run(args, env=env, capture_output=True, timeout=600)
    if result.returncode: raise RuntimeError('Falló la herramienta PostgreSQL. Verifica el servicio, los permisos y el espacio disponible.')
    return result

def create_backup(config, destination=None):
    db = config['database']
    folder = Path(destination or config.get('backup_directory') or ROOT / 'backups').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = folder / f"{db['name']}-{stamp}.backup"
    temporary = target.with_suffix('.partial')
    try:
        run([str(BIN / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-privileges', '--file', str(temporary)], db_env(config))
        run([str(BIN / 'pg_restore.exe'), '--list', str(temporary)], db_env(config))
        temporary.replace(target)
        metadata = {'format': 1, 'database': db['name'], 'created_at': datetime.now(timezone.utc).isoformat(),
                    'sha256': digest(target), 'size': target.stat().st_size, 'content': 'PostgreSQL; no contiene config.local.json ni contraseñas de conexión'}
        target.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        return target
    finally:
        if temporary.exists(): temporary.unlink()

def verify_backup(path):
    path = Path(path).resolve()
    metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if metadata.get('format') != 1 or metadata['size'] != path.stat().st_size or metadata['sha256'] != digest(path):
        raise ValueError('El respaldo está incompleto o su contenido no coincide con el registro de integridad.')
    run([str(BIN / 'pg_restore.exe'), '--list', str(path)], os.environ.copy())
    return metadata

def restore_new_database(path, config, admin_password, target):
    import re
    if not re.fullmatch(r'facturacion_recuperada_\d{14}', target): raise ValueError('El nombre de recuperación debe tener el formato facturacion_recuperada_AAAAMMDDhhmmss.')
    verify_backup(path)
    db = config['database']
    connection = {'host': db['host'], 'port': db['port'], 'dbname': 'postgres', 'user': 'postgres', 'password': admin_password}
    with psycopg.connect(**connection, autocommit=True) as conn:
        if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (target,)).fetchone():
            raise ValueError('La base de destino ya existe. Se canceló la restauración para no sobrescribir datos.')
        conn.execute(sql.SQL('CREATE DATABASE {} OWNER facturacion_admin').format(sql.Identifier(target)))
    restore_config = {'database': {**db, 'name': target, 'user': 'postgres', 'password': admin_password}}
    env = db_env(restore_config)
    env['PGOPTIONS'] = '-c role=facturacion_admin'
    run([str(BIN / 'pg_restore.exe'), '--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges', '--dbname', target, str(Path(path).resolve())], env)
    with psycopg.connect(**{**connection, 'dbname': target}) as conn:
        counts = {table: conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                  for table in ['core_customer', 'core_product', 'core_document', 'core_stockmovement', 'core_payment', 'auth_user']}
    return counts

def automatic_backup(config, root=ROOT):
    if not config.get('backup_directory'): return
    status_file = root / 'backup-status.json'
    if not LOCK.acquire(blocking=False): return
    try:
        previous = json.loads(status_file.read_text(encoding='utf-8')) if status_file.exists() else {}
        today = datetime.now(ZoneInfo('America/Lima')).date().isoformat()
        if previous.get('date') == today and previous.get('ok') and Path(previous.get('path', '')).is_file(): return
        try:
            path = create_backup(config)
            status = {'date': today, 'ok': True, 'path': str(path), 'at': datetime.now(timezone.utc).isoformat()}
        except Exception:
            status = {'date': today, 'ok': False, 'at': datetime.now(timezone.utc).isoformat(), 'message': 'No se completó el respaldo. Revisa almacenamiento y PostgreSQL.'}
        temporary = status_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(status), encoding='utf-8')
        temporary.replace(status_file)
    finally: LOCK.release()

if __name__ == '__main__':
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk(); root.withdraw()
    try:
        config = read_config()
        folder = filedialog.askdirectory(title='Selecciona dónde guardar el respaldo (preferentemente otro disco)')
        if folder:
            path = create_backup(config, folder)
            messagebox.showinfo('Respaldo completado', f'Se verificó la estructura e integridad del archivo.\n{path}\n\nLa restauración se comprueba con Restaurar.cmd.')
    except Exception as exc: messagebox.showerror('Respaldo no completado', str(exc))
