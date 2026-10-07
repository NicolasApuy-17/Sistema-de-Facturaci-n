"""Contraseña del PFX cifrada para el usuario Windows mediante DPAPI."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from django.core.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def protect(data, decrypt=False):
    if os.name != 'nt': raise ValidationError('La configuración cifrada requiere Windows y el usuario que la guardó.')
    source = ctypes.create_string_buffer(data)
    input_blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = Blob()
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    operation = api.CryptUnprotectData if decrypt else api.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob)):
        raise ValidationError('No se pudo procesar la contraseña cifrada. Ejecuta el asistente con el mismo usuario Windows.')
    try: return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(output_blob.data)

def read_certificate_settings():
    path = ROOT / 'sunat.local.json'
    if not path.exists(): return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('environment') != 'BETA': raise ValueError()
        if data.get('demo', True): return None
        return data['certificate'], protect(base64.b64decode(data['password_dpapi'], validate=True), decrypt=True).decode('utf-8')
    except (OSError, ValueError, KeyError):
        raise ValidationError('Revisa Configurar SUNAT beta.cmd. No se pudo leer la configuración local.') from None
