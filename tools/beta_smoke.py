"""Una única prueba de red beta con datos sintéticos; no conecta a PostgreSQL."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import secrets
import io
import zipfile
import sys
from types import SimpleNamespace as Data
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.fiscal.ubl import build_preview, CBC
from core.fiscal.signing import demo_certificate, sign_xml
from core.fiscal.soap import package, send_bill, BetaError
from core.fiscal import soap
from lxml import etree

number = secrets.randbelow(90_000_000) + 1_000_000
ruc = '20100066603'  # RUC usado en los ejemplos públicos del manual SUNAT.
line = Data(description='BOLSA ALIMENTICIA DE PRUEBA', sku='PRUEBA-01', unit='NIU', quantity=Decimal('1'), price=Decimal('118'), tax_rate=Decimal('18'), tax_category='10', package_use='ALIMENTO', subtotal=Decimal('100'), tax=Decimal('18'), total=Decimal('118'))
doc = Data(pk=number, kind='FACTURA', status='BORRADOR', reference=None, reference_id=None, date=datetime.now(ZoneInfo('America/Lima')).date(),
    due_date=None, customer_document_type='RUC', customer_document=ruc, customer_name='CLIENTE SINTETICO DE PRUEBA', customer_address='DIRECCION DE PRUEBA',
    lines=Data(order_by=lambda key: [line]), subtotal=Decimal('100'), tax=Decimal('18'), total=Decimal('118'))
company = Data(ruc=ruc, name='EMISOR SINTETICO DE PRUEBA', address='DIRECCION DE PRUEBA', ubigeo='150101')
root = etree.fromstring(build_preview(doc, company))
note = root.find('{' + CBC + '}Note'); note.set('languageLocaleID', '1000'); note.text = 'CIENTO DIECIOCHO CON 00/100 SOLES'
key, cert = demo_certificate(ruc)
signed, _ = sign_xml(etree.tostring(root), company, key, cert)
filename = f'{ruc}-01-FPRV-{number}.zip'
folder = ROOT / 'work' / 'beta-smoke'; folder.mkdir(parents=True, exist_ok=True)
(folder / filename.replace('.zip', '.xml')).write_bytes(signed)
payload = package(filename, signed)
(folder / filename).write_bytes(payload)
try:
    original_parser = soap.parse_cdr
    def inspect_cdr(content, name):
        (folder / ('R-' + name)).write_bytes(content)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive: print('Archivos de la respuesta sintética: ' + ', '.join(archive.namelist()))
        except zipfile.BadZipFile: pass
        return original_parser(content, name)
    soap.parse_cdr = inspect_cdr
    content, code, description = send_bill(filename, payload, ruc)
    (folder / ('R-' + filename)).write_bytes(content)
    print(f'Respuesta beta: código {code}. {description}')
except BetaError as exc:
    print(f'No se pudo confirmar aceptación en beta: {exc}')
    sys.exit(2)
