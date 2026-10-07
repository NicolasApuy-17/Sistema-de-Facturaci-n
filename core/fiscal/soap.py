"""Cliente exclusivo beta. No acepta endpoints configurables ni redirecciones."""
import base64
import io
import re
import socket
import urllib.error
import urllib.request
import zipfile
from lxml import etree

BETA_URL = 'https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService'
SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
SERVICE = 'http://service.sunat.gob.pe'
WSSE = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
CAC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
APP = 'urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2'
LIMIT = 8_000_000

class BetaError(Exception):
    def __init__(self, message, uncertain=False, code=''):
        super().__init__(message)
        self.uncertain, self.code = uncertain, code

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

def xml_tree(data):
    if len(data) > LIMIT or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise BetaError('Respuesta XML no permitida.', uncertain=True)
    try: return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError: raise BetaError('SUNAT devolvió una respuesta XML inválida.', uncertain=True) from None

def package(filename, xml):
    if not re.fullmatch(r'\d{11}-(01|07|08)-F[A-Z0-9]{3}-\d{1,8}\.zip', filename): raise BetaError('Nombre de archivo beta no válido.')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive: archive.writestr(filename[:-4] + '.xml', xml)
    return stream.getvalue()

def envelope(filename, payload, ruc):
    root = etree.Element('{' + SOAP + '}Envelope', nsmap={'soapenv': SOAP, 'ser': SERVICE, 'wsse': WSSE})
    security = etree.SubElement(etree.SubElement(root, '{' + SOAP + '}Header'), '{' + WSSE + '}Security')
    token = etree.SubElement(security, '{' + WSSE + '}UsernameToken')
    etree.SubElement(token, '{' + WSSE + '}Username').text = ruc + 'MODDATOS'
    etree.SubElement(token, '{' + WSSE + '}Password', Type='http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText').text = 'MODDATOS'
    send = etree.SubElement(etree.SubElement(root, '{' + SOAP + '}Body'), '{' + SERVICE + '}sendBill')
    etree.SubElement(send, 'fileName').text = filename
    etree.SubElement(send, 'contentFile').text = base64.b64encode(payload).decode('ascii')
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8')

def parse_cdr(content, filename):
    if len(content) > LIMIT: raise BetaError('CDR demasiado grande.', uncertain=True)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            all_entries = archive.infolist()
            entries = [entry for entry in all_entries if not entry.is_dir()]
            if len(all_entries) > 10 or len(entries) != 1 or entries[0].filename != 'R-' + filename[:-4] + '.xml' or entries[0].file_size > LIMIT:
                raise BetaError('El CDR no corresponde al archivo enviado.', uncertain=True)
            with archive.open(entries[0]) as stream: data = stream.read(LIMIT + 1)
    except (zipfile.BadZipFile, RuntimeError, OSError): raise BetaError('El CDR recibido no es un ZIP válido.', uncertain=True) from None
    tree = xml_tree(data)
    if tree.tag != '{' + APP + '}ApplicationResponse': raise BetaError('El archivo recibido no es un CDR UBL.', uncertain=True)
    ns = {'cac': CAC, 'cbc': CBC}
    responses = tree.findall('{' + CAC + '}DocumentResponse')
    expected_id = '-'.join(filename[:-4].split('-')[2:])
    expected_ruc = filename.split('-')[0]
    if len(responses) != 1: raise BetaError('CDR con respuesta ambigua.', uncertain=True)
    response = responses[0]
    ref = response.findtext('cac:DocumentReference/cbc:ID', namespaces=ns)
    receiver = tree.findtext('cac:ReceiverParty/cac:PartyIdentification/cbc:ID', namespaces=ns)
    if ref != expected_id or receiver != expected_ruc: raise BetaError('Documento o RUC del CDR no coincide.', uncertain=True)
    code = response.findtext('cac:Response/cbc:ResponseCode', namespaces=ns) or ''
    if not re.fullmatch(r'\d{1,5}', code): raise BetaError('Código de respuesta CDR inválido.', uncertain=True)
    description = response.findtext('cac:Response/cbc:Description', namespaces=ns) or ''
    notes = tree.findall('{' + CBC + '}Note')
    message = description + ''.join(' · ' + (note.text or '') for note in notes)
    return code, message[:1000]

def parse_response(data, filename):
    tree = xml_tree(data)
    if tree.tag != '{' + SOAP + '}Envelope': raise BetaError('Respuesta SOAP no reconocida.', uncertain=True)
    body = tree.find('{' + SOAP + '}Body')
    if body is None: raise BetaError('Respuesta SOAP incompleta.', uncertain=True)
    fault = body.find('{' + SOAP + '}Fault')
    if fault is not None:
        raw_code = fault.findtext('faultcode') or ''
        match = re.search(r'(?:^|[.:])(\d{1,5})$', raw_code)
        code = match.group(1) if match else ''
        # No mostrar faultstring: puede repetir datos de la solicitud.
        raise BetaError('SUNAT devolvió un error SOAP' + (f' (código {code}).' if code else '.'), code=code)
    result = body.find('{' + SERVICE + '}sendBillResponse')
    if result is None: raise BetaError('SUNAT no devolvió sendBillResponse.', uncertain=True)
    values = result.xpath('./*[local-name()="applicationResponse"]')
    if len(values) != 1: raise BetaError('No se recibió una constancia.', uncertain=True)
    try: content = base64.b64decode(''.join((values[0].text or '').split()), validate=True)
    except ValueError: raise BetaError('Constancia con codificación inválida.', uncertain=True) from None
    code, message = parse_cdr(content, filename)
    return content, code, message

def send_bill(filename, payload, ruc):
    request = urllib.request.Request(BETA_URL, data=envelope(filename, payload, ruc), headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': 'urn:sendBill'})
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=35) as response: data = response.read(LIMIT + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 500: data = exc.read(LIMIT + 1)
        else: raise BetaError(f'Servicio beta no disponible (HTTP {exc.code}).', uncertain=True) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise BetaError('No se obtuvo respuesta. El envío pudo recibirse: conserva el mismo archivo y revisa antes de reintentar.', uncertain=True) from None
    return parse_response(data, filename)
