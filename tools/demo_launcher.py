"""Demo portable Windows. Su clúster no instala servicios ni toca otras bases."""
import json
import ctypes
import msvcrt
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
os.environ['TCL_LIBRARY'] = str(Path(__file__).resolve().parents[2] / 'runtime' / 'python' / 'tcl' / 'tcl8.6')
os.environ['TK_LIBRARY'] = str(Path(__file__).resolve().parents[2] / 'runtime' / 'python' / 'tcl' / 'tk8.6')
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

APP = Path(__file__).resolve().parent.parent
BUNDLE = APP.parent
DATA = BUNDLE / 'data'
def short_path(path):
    function = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    if not function(str(path), buffer, len(buffer)): return Path(path)
    return Path(buffer.value)

PG = short_path(BUNDLE / 'runtime' / 'postgres' / 'bin')
PYTHON = BUNDLE / 'runtime' / 'python' / 'python.exe'
CREATE_HIDDEN = subprocess.CREATE_NO_WINDOW

def command(args, env=None):
    result = subprocess.run([str(x) for x in args], cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_HIDDEN, timeout=120)
    if result.returncode: raise RuntimeError('No se pudo preparar la demostración. Revisa el espacio libre, los permisos de la carpeta y que el ZIP esté completamente extraído.')

def private_file(path):
    account = subprocess.check_output(['whoami'], text=True, creationflags=CREATE_HIDDEN).strip()
    command(['icacls', path, '/inheritance:r', '/grant:r', f'{account}:(F)', '*S-1-5-18:(F)'])

def free(port):
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', port)); return True
        except OSError: return False

def environment(state, owner=False):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('PG') or key.startswith('DJANGO') or key.startswith('DEMO_') or key in ('PYTHONHOME', 'PYTHONPATH'): env.pop(key, None)
    env.update(DJANGO_SETTINGS_MODULE='config.demo_settings', DJANGO_SECRET_KEY=state['secret'], DEMO_SECRET_KEY=state['secret'],
        DEMO_PG_PORT=str(state['pg_port']), DEMO_PG_USER='demo_owner' if owner else 'demo_app',
        DEMO_PG_PASSWORD=state['owner_password'] if owner else state['app_password'], PYTHONUTF8='1')
    return env

class Demo:
    def __init__(self):
        DATA.mkdir(exist_ok=True)
        self.root = tk.Tk(); self.root.title('Control Empresa · Demostración'); self.root.geometry('600x340')
        self.server = None; self.pg_started = False; self.closing = False
        self.lock = (DATA / 'demo.lock').open('a+b'); self.lock.write(b'0'); self.lock.flush(); self.lock.seek(0)
        try: msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            messagebox.showinfo('Demo abierta', 'La demostración ya está abierta en esta carpeta. Usa su ventana para abrir el sistema o cerrarla.')
            self.root.destroy(); self.lock.close(); raise SystemExit(0)
        state_path = DATA / 'demo-state.json'
        if state_path.exists(): self.state = json.loads(state_path.read_text(encoding='utf-8'))
        else:
            self.state = {'pg_port': 55439, 'web_port': 18765, 'secret': secrets.token_urlsafe(64), 'owner_password': secrets.token_urlsafe(40), 'app_password': secrets.token_urlsafe(40)}
            state_path.write_text(json.dumps(self.state), encoding='utf-8'); private_file(state_path)
        frame = ttk.Frame(self.root, padding=24); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Demostración para la empresa', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Datos ficticios · Base independiente · Sin instalación\nUsuario: demo\nContraseña: PruebaEmpresa-2026!', font=('Segoe UI', 11)).pack(anchor='w', pady=16)
        self.status = ttk.Label(frame, text='Preparando la primera apertura. Puede tomar unos minutos.', wraplength=550); self.status.pack(anchor='w', pady=8)
        self.open_button = ttk.Button(frame, text='Abrir sistema', state='disabled', command=self.open); self.open_button.pack(fill='x', pady=6)
        self.close_button = ttk.Button(frame, text='Cerrar demostración', state='disabled', command=self.close); self.close_button.pack(fill='x')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        threading.Thread(target=self.prepare, daemon=True).start()

    def prepare(self):
        try:
            if not str(PG).isascii(): raise RuntimeError('PostgreSQL requiere una ruta sin acentos en esta computadora. Extrae la demo en una carpeta con ruta completa sin acentos y vuelve a abrirla.')
            import psycopg
            from psycopg import sql
            pg_data = DATA / 'postgres'
            if not pg_data.exists():
                pw = DATA / 'init-password.tmp'; pw.write_text(self.state['owner_password'], encoding='ascii'); private_file(pw)
                try: command([PG / 'initdb.exe', '-D', pg_data, '-U', 'demo_owner', '-A', 'scram-sha-256', '--pwfile', pw, '--encoding=UTF8', '--locale=C'])
                finally: pw.unlink(missing_ok=True)
            own_status = subprocess.run([str(PG / 'pg_ctl.exe'), '-D', str(pg_data), 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_HIDDEN)
            if own_status.returncode:
                if not free(self.state['pg_port']): raise RuntimeError('El puerto de la demo está ocupado. Cierra otra copia de la demostración e intenta de nuevo.')
                command([PG / 'pg_ctl.exe', '-D', pg_data, '-l', DATA / 'postgres.log', '-o', f'-h 127.0.0.1 -p {self.state["pg_port"]}', '-w', 'start'])
            self.pg_started = True
            if not free(self.state['web_port']): raise RuntimeError('El puerto del navegador de la demo está ocupado. Cierra otra copia e intenta de nuevo.')
            connection = dict(host='127.0.0.1', port=self.state['pg_port'], user='demo_owner', password=self.state['owner_password'])
            with psycopg.connect(dbname='postgres', **connection, autocommit=True) as conn:
                if not conn.execute("SELECT 1 FROM pg_database WHERE datname='facturacion_demo'").fetchone(): conn.execute('CREATE DATABASE facturacion_demo')
                if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='demo_app'").fetchone():
                    conn.execute(sql.SQL('CREATE ROLE demo_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Literal(self.state['app_password'])))
            env = environment(self.state, owner=True)
            command([PYTHON, APP / 'manage.py', 'migrate', '--noinput'], env)
            with psycopg.connect(dbname='facturacion_demo', **connection) as conn:
                conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                conn.execute('GRANT CONNECT ON DATABASE facturacion_demo TO demo_app')
                conn.execute('GRANT USAGE ON SCHEMA public TO demo_app')
                conn.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO demo_app')
                conn.execute('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO demo_app')
                conn.execute('REVOKE UPDATE, DELETE ON core_auditevent FROM demo_app')
            command([PYTHON, APP / 'tools' / 'seed_demo.py'], environment(self.state))
            os.environ.update(environment(self.state))
            sys.path.insert(0, str(APP))
            from config.wsgi import application
            from waitress import create_server
            self.server = create_server(application, host='127.0.0.1', port=self.state['web_port'], threads=6)
            threading.Thread(target=self.server.run, daemon=True).start()
            self.root.after(0, self.ready)
        except Exception as exc:
            error = str(exc) if isinstance(exc, RuntimeError) else 'No se pudo abrir la demo. Comprueba que la carpeta fue extraída completa y permite escritura.'
            self.root.after(0, lambda: self.failed(error))

    def ready(self):
        self.status.config(text='Lista. Las pruebas se guardan en esta carpeta. Mantén esta ventana abierta mientras usas el sistema.')
        self.open_button.config(state='normal'); self.close_button.config(state='normal'); self.open()

    def failed(self, error):
        self.status.config(text=error); self.close_button.config(state='normal')
        messagebox.showerror('No se pudo abrir la demo', error)

    def open(self): webbrowser.open(f'http://127.0.0.1:{self.state["web_port"]}')

    def close(self):
        if self.closing: return
        if self.close_button['state'] == 'disabled':
            messagebox.showinfo('Preparando', 'Espera a que termine la preparación antes de cerrar la demostración.'); return
        self.closing = True; self.open_button.config(state='disabled'); self.close_button.config(state='disabled'); self.status.config(text='Cerrando el sistema y su base de demostración…')
        def stop():
            if self.server:
                self.server.close(); self.server.task_dispatcher.shutdown(timeout=3)
            if self.pg_started:
                subprocess.run([str(PG / 'pg_ctl.exe'), '-D', str(DATA / 'postgres'), '-m', 'fast', '-w', 'stop'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_HIDDEN, timeout=60)
            self.root.after(0, self.root.destroy)
        threading.Thread(target=stop, daemon=True).start()

def main():
    if os.name != 'nt': raise RuntimeError('La demo es para Windows de 64 bits.')
    demo = Demo()
    try: demo.root.mainloop()
    finally: demo.lock.close()

if __name__ == '__main__': main()
