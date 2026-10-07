"""Asistente de certificado beta. No solicita Clave SOL."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.fiscal.local_config import protect

def main():
    root = tk.Tk(); root.title('Configurar SUNAT beta'); root.geometry('620x420')
    frame = ttk.Frame(root, padding=24); frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Certificado para pruebas', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='El sistema solo enviará al servicio beta de SUNAT. No solicita Clave SOL.\nPuedes usar un certificado de prueba generado en memoria o tu PFX/P12.', wraplength=550).pack(anchor='w', pady=12)
    demo = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text='Usar certificado generado para pruebas (sin validez tributaria)', variable=demo).pack(anchor='w')
    selected = tk.StringVar()
    ttk.Entry(frame, textvariable=selected, state='readonly').pack(fill='x', pady=10)
    def choose():
        name = filedialog.askopenfilename(filetypes=[('Certificado', '*.pfx *.p12')])
        if name: selected.set(name); demo.set(False)
    ttk.Button(frame, text='Seleccionar certificado propio', command=choose).pack(anchor='w')
    ttk.Label(frame, text='Contraseña del certificado propio').pack(anchor='w', pady=(12, 4))
    password = ttk.Entry(frame, show='•'); password.pack(fill='x')
    def save():
        try:
            config = {'environment': 'BETA', 'demo': demo.get()}
            if not demo.get():
                if not Path(selected.get()).is_file(): raise ValueError('Selecciona un certificado.')
                config.update(certificate=selected.get(), password_dpapi=base64.b64encode(protect(password.get().encode('utf-8'))).decode('ascii'))
            path = ROOT / 'sunat.local.json'
            path.write_text(json.dumps(config, indent=2), encoding='utf-8')
            account = subprocess.check_output(['whoami'], text=True).strip()
            result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'{account}:(F)', '*S-1-5-18:(F)'], capture_output=True)
            if result.returncode: raise ValueError('No se pudieron restringir los permisos del archivo.')
            password.delete(0, 'end')
            messagebox.showinfo('Configuración guardada', 'Se guardó la configuración beta. La contraseña está cifrada para este usuario Windows. El certificado se verifica al preparar el documento.')
        except Exception: messagebox.showerror('No se completó', 'Revisa el certificado, el usuario Windows y los permisos de esta carpeta.')
    ttk.Button(frame, text='Guardar configuración beta', command=save).pack(fill='x', pady=20)
    root.mainloop()

if __name__ == '__main__': main()
