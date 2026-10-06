from django.conf import settings
from .models import Company

def readiness():
    import json
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    from pathlib import Path
    company = Company.objects.first()
    status_path = settings.BASE_DIR / 'backup-status.json'
    try: status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    except (OSError, ValueError): status = {}
    backup_ready = False
    backup_description = 'Configura la carpeta con Actualizar.cmd. La copia diaria se realiza mientras la aplicación está abierta.'
    if status.get('ok'):
        try:
            at = datetime.fromisoformat(status['at'])
            backup_ready = at >= datetime.now(timezone.utc) - timedelta(hours=36) and Path(status.get('path', '')).is_file()
            backup_description = 'Última copia: ' + at.astimezone(ZoneInfo('America/Lima')).strftime('%d/%m/%Y %H:%M') + ' (hora de Lima).'
        except (KeyError, ValueError, TypeError): pass
    return [
        {'label': 'Datos de la empresa', 'ready': bool(company and company.ruc and company.address and company.ubigeo and company.regime), 'detail': 'Completa RUC, régimen, razón social, dirección y ubigeo.'},
        {'label': 'Respaldo automático', 'ready': backup_ready, 'detail': backup_description},
        {'label': 'Emisión electrónica CPE y GRE', 'ready': False, 'detail': 'Faltan certificado, credenciales locales, integración y validación de XML/CDR con SUNAT.'},
        {'label': 'Impuestos de bolsas y otros productos', 'ready': False, 'detail': 'Clasifica afectación al IGV y uso de cada producto. Bolsas alimenticias: revisar el supuesto de envase/inocuidad; no se aplica ICBPER automáticamente. Bolsas para llevar compras: ICBPER pendiente.'},
        {'label': 'Instalación en la computadora de la empresa', 'ready': False, 'detail': 'Uso confirmado en una sola computadora. Pendiente comprobar instalación, inicio automático y restauración en el equipo de destino.'},
    ]
