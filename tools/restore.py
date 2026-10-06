from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from backup import read_config, restore_new_database, verify_backup

root = tk.Tk(); root.withdraw()
try:
    path = filedialog.askopenfilename(title='Selecciona el respaldo a comprobar y restaurar', filetypes=[('Respaldo PostgreSQL', '*.backup')])
    if path:
        verify_backup(path)
        password = simpledialog.askstring('Restaurar sin sobrescribir', 'Se creará una base nueva. La base del sistema seguirá intacta.\nContraseña de postgres:', show='•')
        if password:
            target = 'facturacion_recuperada_' + datetime.now().strftime('%Y%m%d%H%M%S')
            counts = restore_new_database(path, read_config(), password, target)
            messagebox.showinfo('Restauración comprobada', f'Base nueva: {target}\nClientes: {counts["core_customer"]}\nProductos: {counts["core_product"]}\nDocumentos: {counts["core_document"]}\n\nNo se cambió la conexión del sistema. Conserva esta base hasta decidir si necesitas recuperar datos.')
except Exception as exc: messagebox.showerror('No se completó la restauración', str(exc))
