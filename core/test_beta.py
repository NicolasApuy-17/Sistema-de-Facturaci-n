import base64
from datetime import timedelta
import io
import zipfile
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase
from django.utils import timezone
from lxml import etree
from signxml import XMLVerifier
from . import test_fiscal
from .models import BetaSubmission, StockMovement
from .fiscal.signing import demo_certificate, load_certificate, sign_xml, DS
from .fiscal.ubl import build_preview, NS
from .fiscal.workflow import prepare_beta, submit_beta, recover_interrupted
from .fiscal.soap import BetaError, parse_response, parse_cdr, envelope, SOAP, SERVICE, APP, CAC, CBC, BETA_URL, send_bill

def cdr(filename, code='0', receiver=None, ref=None):
    root = etree.Element('{' + APP + '}ApplicationResponse', nsmap={'cac': CAC, 'cbc': CBC})
    receiver_node = etree.SubElement(etree.SubElement(root, '{' + CAC + '}ReceiverParty'), '{' + CAC + '}PartyIdentification')
    etree.SubElement(receiver_node, '{' + CBC + '}ID').text = receiver or filename.split('-')[0]
    document = etree.SubElement(root, '{' + CAC + '}DocumentResponse')
    response = etree.SubElement(document, '{' + CAC + '}Response')
    etree.SubElement(response, '{' + CBC + '}ResponseCode').text = code
    etree.SubElement(response, '{' + CBC + '}Description').text = 'Resultado de prueba'
    etree.SubElement(etree.SubElement(document, '{' + CAC + '}DocumentReference'), '{' + CBC + '}ID').text = ref or '-'.join(filename[:-4].split('-')[2:])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive: archive.writestr('R-' + filename[:-4] + '.xml', etree.tostring(root))
    return stream.getvalue()

def soap_result(content):
    root = etree.Element('{' + SOAP + '}Envelope')
    response = etree.SubElement(etree.SubElement(root, '{' + SOAP + '}Body'), '{' + SERVICE + '}sendBillResponse')
    etree.SubElement(response, 'applicationResponse').text = base64.b64encode(content).decode('ascii')
    return etree.tostring(root)

class BetaTests(TestCase):
    # Reutilizar solo la preparación de datos, no heredar todas las pruebas.
    setUp = test_fiscal.FiscalPreviewTests.setUp
    draft = test_fiscal.FiscalPreviewTests.draft

    def prepare(self):
        with patch('core.fiscal.workflow.read_certificate_settings', return_value=None): return prepare_beta(self.draft().pk, self.user)

    def test_signature_verifies_and_detects_modification(self):
        doc = self.draft()
        key, cert = demo_certificate(self.company.ruc)
        signed, _ = sign_xml(build_preview(doc, self.company), self.company, key, cert)
        pem = cert.public_bytes(serialization.Encoding.PEM)
        XMLVerifier().verify(signed, x509_cert=pem)
        root = etree.fromstring(signed)
        self.assertEqual(len(root.findall('.//{' + DS + '}Signature')), 1)
        root.xpath('./cac:InvoiceLine/cac:Item/cbc:Description', namespaces=NS)[0].text = 'Alterado'
        with self.assertRaises(Exception): XMLVerifier().verify(etree.tostring(root), x509_cert=pem)

    def test_preparation_is_idempotent_and_does_not_register_sale(self):
        submission = self.prepare()
        self.assertEqual(prepare_beta(submission.document_id, self.user).pk, submission.pk)
        self.assertEqual(submission.document.status, 'BORRADOR')
        self.assertEqual(submission.document.sunat_status, 'NO_ENVIADO')
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(BetaSubmission.objects.count(), 1)
        self.assertTrue(submission.demo_certificate)

    def test_accepted_cdr_is_saved_and_repeat_does_not_resend(self):
        submission = self.prepare()
        with patch('core.fiscal.workflow.send_bill', return_value=(cdr(submission.filename), '0', 'Aceptado beta')) as sender:
            result = submit_beta(submission.pk, self.user)
            submit_beta(submission.pk, self.user)
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(result.state, 'ACEPTADO')
        self.assertTrue(result.cdr_zip)
        self.assertEqual(result.document.sunat_status, 'NO_ENVIADO')

    def test_rejection_is_not_acceptance(self):
        submission = self.prepare()
        with patch('core.fiscal.workflow.send_bill', return_value=(cdr(submission.filename, '2335'), '2335', 'Rechazado')):
            self.assertEqual(submit_beta(submission.pk, self.user).state, 'RECHAZADO')

    def test_timeout_requires_explicit_retry_of_same_bytes(self):
        submission = self.prepare(); payload = bytes(submission.payload_zip)
        with patch('core.fiscal.workflow.send_bill', side_effect=BetaError('Sin respuesta', uncertain=True)):
            self.assertEqual(submit_beta(submission.pk, self.user).state, 'INCIERTO')
        with self.assertRaises(ValidationError): submit_beta(submission.pk, self.user)
        with patch('core.fiscal.workflow.send_bill', return_value=(cdr(submission.filename), '0', 'Aceptado')) as sender:
            submit_beta(submission.pk, self.user, retry=True)
            self.assertEqual(sender.call_args.args[1], payload)

    def test_duplicate_error_does_not_mark_as_accepted(self):
        submission = self.prepare()
        with patch('core.fiscal.workflow.send_bill', side_effect=BetaError('Error duplicado', code='1033')):
            result = submit_beta(submission.pk, self.user)
        self.assertEqual((result.state, result.response_code), ('ERROR', '1033'))

    def test_prepared_xml_integrity_is_checked_before_send(self):
        submission = self.prepare()
        BetaSubmission.objects.filter(pk=submission.pk).update(signed_xml=b'alterado')
        with patch('core.fiscal.workflow.send_bill') as sender:
            with self.assertRaises(ValidationError): submit_beta(submission.pk, self.user)
            sender.assert_not_called()

    def test_second_send_cannot_claim_in_progress_submission(self):
        submission = self.prepare()
        def respond(*args):
            with self.assertRaises(ValidationError): submit_beta(submission.pk, self.user)
            return cdr(submission.filename), '0', 'Aceptado'
        with patch('core.fiscal.workflow.send_bill', side_effect=respond) as sender: submit_beta(submission.pk, self.user)
        self.assertEqual(sender.call_count, 1)

    def test_interrupted_send_can_be_marked_uncertain_after_three_minutes(self):
        submission = self.prepare()
        BetaSubmission.objects.filter(pk=submission.pk).update(state='ENVIANDO', last_attempt_at=timezone.now())
        with self.assertRaises(ValidationError): recover_interrupted(submission.pk, self.user)
        BetaSubmission.objects.filter(pk=submission.pk).update(last_attempt_at=timezone.now() - timedelta(minutes=4))
        self.assertEqual(recover_interrupted(submission.pk, self.user).state, 'INCIERTO')

    def test_prepare_and_send_routes_require_post_and_confirmation(self):
        doc = self.draft()
        url = f'/comprobantes/{doc.pk}/beta/'
        self.assertEqual(self.client.get(url + 'preparar/').status_code, 405)
        with patch('core.fiscal.workflow.read_certificate_settings', return_value=None):
            self.assertEqual(self.client.post(url + 'preparar/').status_code, 302)
        self.assertEqual(self.client.get(url).status_code, 200)
        for artifact in ['xml', 'zip']: self.assertEqual(self.client.get(url + 'archivo/' + artifact + '/').status_code, 200)
        with patch('core.fiscal.workflow.send_bill') as sender:
            self.client.post(url + 'enviar/')
            sender.assert_not_called()
        self.user.is_staff = False; self.user.save()
        self.assertEqual(self.client.get(url).status_code, 403)

class SoapTests(SimpleTestCase):
    filename = '20123456789-01-FPRV-1.zip'
    def test_beta_envelope_uses_only_public_beta_credentials(self):
        data = envelope(self.filename, b'ZIP', '20123456789')
        self.assertIn(b'20123456789MODDATOS', data)
        self.assertIn(b'fileName', data)

    def test_accepted_and_rejected_cdr_are_parsed(self):
        for code in ['0', '2335']:
            _, actual, _ = parse_response(soap_result(cdr(self.filename, code)), self.filename)
            self.assertEqual(actual, code)

    def test_wrong_document_or_ruc_is_not_accepted(self):
        for content in [cdr(self.filename, receiver='20987654321'), cdr(self.filename, ref='FPRV-999')]:
            with self.assertRaises(BetaError): parse_cdr(content, self.filename)

    def test_invalid_zip_and_xml_entities_are_rejected(self):
        for data in [b'not xml', b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><x>&a;</x>']:
            with self.assertRaises(BetaError): parse_response(data, self.filename)
        with self.assertRaises(BetaError): parse_cdr(b'not zip', self.filename)

    def test_cdr_allows_empty_directories_but_rejects_extra_files(self):
        valid = cdr(self.filename)
        source = zipfile.ZipFile(io.BytesIO(valid))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('dummy/', b'')
            archive.writestr(source.namelist()[0], source.read(source.namelist()[0]))
        self.assertEqual(parse_cdr(stream.getvalue(), self.filename)[0], '0')
        with zipfile.ZipFile(stream, 'a') as archive: archive.writestr('otro.xml', b'<x/>')
        with self.assertRaises(BetaError): parse_cdr(stream.getvalue(), self.filename)

    def test_soap_fault_is_sanitized(self):
        data = b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault><faultcode>soap:Client.1033</faultcode><faultstring>SECRET USER DETAILS</faultstring></s:Fault></s:Body></s:Envelope>'
        with self.assertRaises(BetaError) as context: parse_response(data, self.filename)
        self.assertEqual(context.exception.code, '1033')
        self.assertNotIn('SECRET', str(context.exception))

    def test_transport_has_fixed_beta_endpoint_and_preserves_tls_defaults(self):
        from unittest.mock import MagicMock
        response = MagicMock(); response.__enter__.return_value = response; response.read.return_value = soap_result(cdr(self.filename))
        opener = MagicMock(); opener.open.return_value = response
        with patch('core.fiscal.soap.urllib.request.build_opener', return_value=opener): send_bill(self.filename, b'ZIP', '20123456789')
        self.assertEqual(opener.open.call_args.args[0].full_url, BETA_URL)

class CertificateTests(SimpleTestCase):
    def test_local_pfx_requires_correct_password_and_ruc(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from cryptography.hazmat.primitives.serialization import pkcs12
        key, cert = demo_certificate('20123456789')
        data = pkcs12.serialize_key_and_certificates(b'prueba', key, cert, None, serialization.BestAvailableEncryption(b'clave-de-prueba'))
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'certificado.pfx'; path.write_bytes(data)
            self.assertEqual(load_certificate(path, 'clave-de-prueba', '20123456789')[1].serial_number, cert.serial_number)
            with self.assertRaises(ValidationError): load_certificate(path, 'incorrecta', '20123456789')
            with self.assertRaises(ValidationError): load_certificate(path, 'clave-de-prueba', '20987654321')
