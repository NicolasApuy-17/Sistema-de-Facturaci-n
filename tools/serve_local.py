"""Inicio local, comprobación de migraciones y respaldo diario mientras está abierto."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    if not (ROOT / 'config.local.json').exists(): raise RuntimeError('Primero abre Configurar.cmd.')
    config = json.loads((ROOT / 'config.local.json').read_text(encoding='utf-8'))
    logs = ROOT / 'logs'; logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.WARNING, handlers=[RotatingFileHandler(logs / 'application.log', maxBytes=2_000_000, backupCount=5, encoding='utf-8')])
    from config.wsgi import application
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    try:
        connection.ensure_connection()
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise RuntimeError('Hay una actualización pendiente. Cierra el sistema, abre Actualizar.cmd y después vuelve a iniciarlo.')
    except RuntimeError: raise
    except Exception: raise RuntimeError('No se pudo conectar con PostgreSQL. Comprueba que el servicio esté activo.') from None
    finally: connection.close()
    port = config.get('port', 8765)
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1', port))
        except OSError: raise RuntimeError(f'El puerto {port} está ocupado. Si el sistema ya está abierto, utiliza su ventana del navegador.') from None
    stop = threading.Event()
    def backup_worker():
        from backup import automatic_backup
        while not stop.is_set():
            automatic_backup(config)
            stop.wait(3600)
    threading.Thread(target=backup_worker, daemon=True).start()
    if '--no-browser' not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    from waitress import serve
    try: serve(application, host='127.0.0.1', port=port, threads=6)
    finally: stop.set()

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: pass
    except Exception as exc:
        if '--background' in sys.argv:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror('Control Empresa', str(exc))
        else: print(str(exc), file=sys.stderr)
        sys.exit(1)
