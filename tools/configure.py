"""Asistente local: nunca imprime ni solicita contraseñas en el chat."""
import json
import os
import secrets
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def prepare(values):
    name = values['database']
    if name not in ('facturacion_dev', 'facturacion_prod'):
        raise ValueError('Selecciona facturacion_dev o facturacion_prod.')
    if len(values['password']) < 12:
        raise ValueError('La contraseña del administrador del sistema debe tener al menos 12 caracteres.')
    from django.conf import settings
    if not settings.configured:
        settings.configure(AUTH_PASSWORD_VALIDATORS=[
            {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
            {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
            {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}])
    from django.contrib.auth.password_validation import validate_password
    validate_password(values['password'])
    local_path = ROOT / 'config.local.json'
    previous = json.loads(local_path.read_text(encoding='utf-8')) if local_path.exists() else None
    if previous and previous['database']['name'] != name:
        raise ValueError('Esta carpeta ya está configurada para otra base. Usa una copia independiente del proyecto.')
    port = values.get('port', 5432)
    connection = dict(host='127.0.0.1', port=port, dbname=name, user='postgres', password=values['postgres_password'])
    with psycopg.connect(**connection, autocommit=True) as conn:
        row = conn.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (name,)).fetchone()
        if not row or row[0] != 'facturacion_admin':
            raise ValueError('La base debe existir y pertenecer a facturacion_admin. Revisa el paso 5 de la guía.')
    new_config = previous or {'secret_key': secrets.token_urlsafe(64), 'allowed_hosts': [], 'port': 8765,
        'database': {'host': '127.0.0.1', 'port': port, 'name': name, 'user': name + '_app', 'password': secrets.token_urlsafe(40)}}
    env = os.environ.copy()
    env.update(PGDATABASE=name, PGUSER='postgres', PGPASSWORD=values['postgres_password'], PGHOST='127.0.0.1', PGPORT=str(port),
               PGOPTIONS='-c role=facturacion_admin', DJANGO_SECRET_KEY=new_config['secret_key'])
    # Las tablas se crean como el propietario, no como el usuario cotidiano de la aplicación.
    result = subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('No se pudo preparar la estructura de la base. Comprueba los permisos de facturacion_admin y el servicio PostgreSQL.')
    role = new_config['database']['user']
    with psycopg.connect(**connection) as conn:
        exists = conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
        if exists and not previous:
            raise ValueError('Ya existe el usuario de aplicación pero falta la configuración local. No se cambió su contraseña; restaura la configuración o revisa la instalación.')
        if not exists:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}').format(
                sql.Identifier(role), sql.Literal(new_config['database']['password'])))
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(name), sql.Identifier(role)))
        conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('REVOKE UPDATE, DELETE ON core_auditevent FROM {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE facturacion_admin IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE facturacion_admin IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}').format(sql.Identifier(role)))
    with psycopg.connect(host='127.0.0.1', port=port, dbname=name, user=role, password=new_config['database']['password']):
        pass
    # Se escribe solo después de verificar la conexión. La contraseña postgres nunca se guarda.
    local_path.write_text(json.dumps(new_config, indent=2), encoding='utf-8')
    # Limitar el archivo al usuario de Windows y SYSTEM; no mostrar secretos.
    if os.name == 'nt':
        account = subprocess.check_output(['whoami'], text=True).strip()
        acl = subprocess.run(['icacls', str(local_path), '/inheritance:r', '/grant:r', f'{account}:(F)', '*S-1-5-18:(F)'], capture_output=True)
        if acl.returncode:
            raise ValueError('La conexión está configurada, pero no se pudo restringir el archivo de credenciales. Revisa sus permisos antes de continuar.')
    # Un proceso nuevo carga los settings completos, separados del asistente gráfico.
    admin_env = os.environ.copy()
    admin_env.update(FACT_ADMIN_NAME=values['username'], FACT_ADMIN_PASSWORD=values['password'])
    result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'create_admin.py')], cwd=ROOT, env=admin_env,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('La base está preparada, pero el usuario de acceso ya existe o no pudo crearse. No se modificó ninguna contraseña existente.')
    subprocess.run([sys.executable, 'manage.py', 'collectstatic', '--noinput'], cwd=ROOT, check=True, capture_output=True)

def main():
    root = tk.Tk()
    root.title('Configurar · Control Empresa')
    root.geometry('570x610')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=25)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Preparar el sistema local', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Conexión a PostgreSQL y primer administrador.\nLas contraseñas se ingresan únicamente en esta ventana.', wraplength=500).pack(anchor='w', pady=12)
    fields = {}
    for key, label, default, hidden in [
        ('database', 'Base de datos (desarrollo o empresa)', 'facturacion_dev', False),
        ('postgres_password', 'Contraseña de postgres (solo para preparar la instalación)', '', True),
        ('username', 'Usuario para ingresar al sistema', '', False),
        ('password', 'Contraseña del sistema (mínimo 12 caracteres)', '', True),
        ('confirm', 'Confirmar contraseña del sistema', '', True)]:
        ttk.Label(frame, text=label).pack(anchor='w', pady=(10, 4))
        widget = ttk.Combobox(frame, values=['facturacion_dev', 'facturacion_prod'], state='readonly') if key == 'database' else ttk.Entry(frame, show='•' if hidden else '')
        if key == 'database': widget.set(default)
        else: widget.insert(0, default)
        widget.pack(fill='x')
        fields[key] = widget
    status = ttk.Label(frame, text='PostgreSQL debe estar instalado y la base creada.', wraplength=490)
    status.pack(anchor='w', pady=18)
    def finished(error):
        button.config(state='normal')
        fields['postgres_password'].delete(0, 'end')
        if error:
            status.config(text='Revisa los datos e intenta nuevamente.')
            messagebox.showerror('No se completó la configuración', error)
        else:
            status.config(text='Listo. Abre Iniciar.cmd para entrar al sistema.')
            messagebox.showinfo('Sistema preparado', 'Conexión verificada y administrador creado.\nAbre Iniciar.cmd para comenzar.')
    def execute():
        values = {key: field.get().strip() if key in ('username', 'database') else field.get() for key, field in fields.items()}
        if not values['username'] or values['password'] != values['confirm']:
            messagebox.showerror('Revisa los datos', 'Completa el usuario y confirma que ambas contraseñas del sistema coincidan.')
            return
        button.config(state='disabled')
        status.config(text='Verificando la conexión y preparando tablas…')
        def worker():
            try: prepare(values)
            except psycopg.Error:
                root.after(0, finished, 'No se pudo conectar o preparar PostgreSQL. Verifica la contraseña de postgres, el puerto 5432 y que la base exista.')
            except Exception as exc:
                root.after(0, finished, str(exc))
            else: root.after(0, finished, None)
        threading.Thread(target=worker, daemon=True).start()
    button = ttk.Button(frame, text='Verificar y preparar sistema', command=execute)
    button.pack(fill='x')
    ttk.Label(frame, text='No solicita Clave SOL ni emite comprobantes ante SUNAT.', wraplength=490).pack(anchor='w', pady=14)
    root.mainloop()

if __name__ == '__main__': main()
