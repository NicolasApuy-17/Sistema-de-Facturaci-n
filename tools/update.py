"""Actualizar sin pedir credenciales en el chat ni guardar la contraseña postgres."""
import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path
import psycopg
from psycopg import sql
from backup import create_backup, read_config

ROOT = Path(__file__).resolve().parent.parent

def update(config, password):
    db = config['database']
    # Primero comprobar la contraseña, antes de cualquier cambio.
    connection = dict(host=db['host'], port=db['port'], dbname=db['name'], user='postgres', password=password)
    with psycopg.connect(**connection) as conn:
        owner = conn.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (db['name'],)).fetchone()[0]
        if owner != 'facturacion_admin': raise ValueError('La base no pertenece a facturacion_admin.')
    backup = create_backup(config)
    env = os.environ.copy()
    env.update(PGDATABASE=db['name'], PGUSER='postgres', PGPASSWORD=password, PGHOST=db['host'], PGPORT=str(db['port']),
               PGOPTIONS='-c role=facturacion_admin', PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=ROOT, env=env, capture_output=True)
    if result.returncode: raise RuntimeError(f'No se completó la actualización. El respaldo está conservado en {backup}.')
    with psycopg.connect(**connection) as conn:
        role = sql.Identifier(db['user'])
        conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}').format(role))
        conn.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(role))
        # La auditoría no se modifica ni elimina con el usuario cotidiano.
        conn.execute(sql.SQL('REVOKE UPDATE, DELETE ON core_auditevent FROM {}').format(role))
    env.pop('PGOPTIONS', None)
    for key in ['PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGHOST', 'PGPORT']: env.pop(key, None)
    result = subprocess.run([sys.executable, 'manage.py', 'collectstatic', '--noinput'], cwd=ROOT, env=env, capture_output=True)
    if result.returncode: raise RuntimeError('La base se actualizó, pero no se pudieron preparar los archivos de interfaz.')
    return backup

def main():
    root = tk.Tk(); root.withdraw()
    try:
        config = read_config()
        password = simpledialog.askstring('Actualizar Control Empresa', 'Cierra el sistema antes de continuar.\nContraseña de postgres (no se guardará):', show='•')
        if not password: return
        if not config.get('backup_directory'):
            folder = filedialog.askdirectory(title='Carpeta para respaldos diarios (preferentemente otro disco)')
            if folder:
                config['backup_directory'] = folder
                (ROOT / 'config.local.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
        backup = update(config, password)
        messagebox.showinfo('Actualización completada', f'Tus datos se conservaron.\nRespaldo previo: {backup}\n\nAbre Iniciar.cmd para continuar.')
    except psycopg.Error: messagebox.showerror('No se completó', 'Verifica la contraseña de postgres y que PostgreSQL esté activo.')
    except Exception as exc: messagebox.showerror('No se completó', str(exc))

if __name__ == '__main__': main()
