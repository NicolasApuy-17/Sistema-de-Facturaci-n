"""Firma XMLDSig RSA-SHA256 y verificación local. Certificado demo solo para beta."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.core.exceptions import ValidationError
from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods
from signxml.algorithms import CanonicalizationMethod
from .ubl import CAC, CBC, child, schema

EXT = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
DS = 'http://www.w3.org/2000/09/xmldsig#'

def demo_certificate(ruc):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'CERTIFICADO DE PRUEBA SIN VALIDEZ TRIBUTARIA'), x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ruc)])
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=7)).sign(key, hashes.SHA256())
    return key, cert

def load_certificate(path, password, ruc):
    try:
        data = Path(path).read_bytes()
        if len(data) > 2_000_000: raise ValueError()
        key, cert, _ = pkcs12.load_key_and_certificates(data, password.encode('utf-8') if password else None)
    except (OSError, ValueError):
        raise ValidationError('No se pudo abrir el certificado PFX/P12. Revisa el archivo y su contraseña en el asistente local.') from None
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048 or cert is None:
        raise ValidationError('Se requiere certificado RSA con clave privada de al menos 2048 bits.')
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
        raise ValidationError('El certificado aún no es válido o está vencido.')
    if ruc not in [attribute.value for attribute in cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)]:
        raise ValidationError('El RUC del certificado no coincide con la empresa.')
    return key, cert

def sign_xml(xml, company, key, cert):
    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True))
    extensions = etree.Element('{' + EXT + '}UBLExtensions', nsmap={'ext': EXT})
    content = etree.SubElement(etree.SubElement(extensions, '{' + EXT + '}UBLExtension'), '{' + EXT + '}ExtensionContent')
    etree.SubElement(content, '{' + DS + '}Signature', nsmap={'ds': DS}, Id='placeholder')
    root.insert(0, extensions)
    reference = etree.Element('{' + CAC + '}Signature')
    child(reference, 'cbc:ID', 'SignatureSP')
    signatory = child(reference, 'cac:SignatoryParty')
    child(child(signatory, 'cac:PartyIdentification'), 'cbc:ID', company.ruc)
    child(child(signatory, 'cac:PartyName'), 'cbc:Name', company.name)
    child(child(child(reference, 'cac:DigitalSignatureAttachment'), 'cac:ExternalReference'), 'cbc:URI', '#SignatureSP')
    supplier = root.find('{' + CAC + '}AccountingSupplierParty')
    root.insert(root.index(supplier), reference)
    signer = XMLSigner(method=methods.enveloped, signature_algorithm='rsa-sha256', digest_algorithm='sha256', c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0)
    pem = cert.public_bytes(serialization.Encoding.PEM)
    signed = signer.sign(root, key=key, cert=pem)
    signature = signed.find('.//{' + DS + '}Signature')
    signature.set('Id', 'SignatureSP')
    # Verificar los bytes finales, no una versión previa a serializar.
    result = etree.tostring(signed, xml_declaration=True, encoding='UTF-8')
    XMLVerifier().verify(result, x509_cert=pem)
    if not schema(etree.QName(signed).localname).validate(signed):
        raise ValidationError('El XML firmado no cumple la estructura UBL.')
    return result, cert.fingerprint(hashes.SHA256()).hex()
