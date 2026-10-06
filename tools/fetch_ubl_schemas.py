"""Descarga puntual de los XSD del estándar UBL 2.1 desde OASIS."""
import hashlib
import json
from pathlib import Path
import urllib.request
from urllib.parse import urljoin, urlparse
from lxml import etree

BASE = 'https://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/'
ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'core' / 'fiscal' / 'schemas'
visited = {}
def fetch(url):
    if url in visited: return
    if not url.startswith(BASE): raise ValueError('Importación fuera del estándar oficial.')
    relative = url[len(BASE):]
    if '..' in relative.split('/'): raise ValueError('Ruta no permitida.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    content = urllib.request.urlopen(request, timeout=45).read()
    visited[url] = hashlib.sha256(content).hexdigest()
    target = TARGET / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    tree = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    for node in tree.xpath('//*[@schemaLocation]'):
        fetch(urljoin(url, node.attrib['schemaLocation']))
for root in ('Invoice', 'CreditNote', 'DebitNote'):
    fetch(BASE + 'maindoc/UBL-' + root + '-2.1.xsd')
(TARGET / 'source.json').write_text(json.dumps({'standard': 'UBL 2.1', 'source': BASE, 'files_sha256': visited,
    'note': 'Estándar original OASIS. El ZIP publicado por SUNAT respondió HTTP 403. Esto valida estructura UBL, no reglas tributarias SUNAT.'}, indent=2), encoding='utf-8')
print(f'Esquemas oficiales OASIS guardados: {len(visited)}')
