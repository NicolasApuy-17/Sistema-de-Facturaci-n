"""Registro persistente de pruebas. No cambia estados fiscales reales ni stock."""
import hashlib
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from lxml import etree
from num2words import num2words
from ..models import BetaSubmission, Company, Document
from ..services import audit
from .ubl import CBC, build_preview, preview_id
from .signing import demo_certificate, load_certificate, sign_xml
from .local_config import read_certificate_settings
from .soap import BetaError, package, send_bill

@transaction.atomic
def prepare_beta(document_id, user):
    doc = Document.objects.select_for_update().get(pk=document_id)
    if doc.kind != 'FACTURA' or doc.status == 'CANCELADO':
        raise ValidationError('Este flujo beta admite facturas al contado. Boletas, notas y GRE se integrarán por sus flujos correspondientes.')
    prior = BetaSubmission.objects.filter(document=doc).first()
    if prior: return prior
    company = Company.objects.first()
    unsigned = build_preview(doc, company)
    root = etree.fromstring(unsigned)
    note = root.find('{' + CBC + '}Note')
    note.set('languageLocaleID', '1000')
    integer, fraction = format(doc.total, '.2f').split('.')
    note.text = num2words(int(integer), lang='es').upper() + f' CON {fraction}/100 SOLES'
    settings = read_certificate_settings()
    key, cert = load_certificate(*settings, company.ruc) if settings else demo_certificate(company.ruc)
    signed, fingerprint = sign_xml(etree.tostring(root), company, key, cert)
    filename = f'{company.ruc}-01-{preview_id(doc)}.zip'
    payload = package(filename, signed)
    submission = BetaSubmission.objects.create(document=doc, ruc=company.ruc, filename=filename, signed_xml=signed,
        payload_zip=payload, sha256=hashlib.sha256(signed).hexdigest(), demo_certificate=not bool(settings),
        certificate_fingerprint=fingerprint, created_by=user)
    audit(user, 'Preparar factura beta', submission)
    return submission

def submit_beta(submission_id, user, retry=False):
    # Bloquear la fila solo para reclamar el envío; no mantener transacción durante la red.
    with transaction.atomic():
        submission = BetaSubmission.objects.select_for_update().get(pk=submission_id)
        if submission.state in ('ACEPTADO', 'RECHAZADO'): return submission
        if submission.document.status == 'CANCELADO': raise ValidationError('La factura interna está cancelada; no se envió la prueba.')
        if submission.state == 'ENVIANDO':
            raise ValidationError('Ya hay un envío en curso. No se envió otra copia.')
        if submission.state in ('INCIERTO', 'ERROR') and not retry:
            raise ValidationError('Revisa la respuesta anterior y confirma el reintento del mismo archivo.')
        import io, zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(bytes(submission.payload_zip))) as archive:
                valid = archive.namelist() == [submission.filename[:-4] + '.xml'] and archive.infolist()[0].file_size < 8_000_000 and archive.read(archive.namelist()[0]) == bytes(submission.signed_xml)
        except (zipfile.BadZipFile, OSError, RuntimeError): valid = False
        if not valid or hashlib.sha256(bytes(submission.signed_xml)).hexdigest() != submission.sha256:
            raise ValidationError('El archivo preparado fue alterado. No se envió.')
        submission.state = 'ENVIANDO'; submission.attempts += 1; submission.last_attempt_at = timezone.now()
        submission.save(update_fields=['state', 'attempts', 'last_attempt_at'])
        owned_attempt = submission.attempts
        audit(user, 'Enviar factura a beta', submission)
    try:
        cdr, code, message = send_bill(submission.filename, bytes(submission.payload_zip), submission.ruc)
    except BetaError as exc:
        state, code, message, cdr = ('INCIERTO' if exc.uncertain else 'ERROR'), exc.code, str(exc), None
    except Exception:
        state, code, message, cdr = 'INCIERTO', '', 'No se pudo finalizar el envío. Conserva el archivo y revisa el estado antes de reintentar.', None
    else: state = 'ACEPTADO' if code == '0' else 'RECHAZADO'
    with transaction.atomic():
        submission = BetaSubmission.objects.select_for_update().get(pk=submission_id)
        if submission.attempts != owned_attempt:
            audit(user, 'Respuesta beta de intento anterior', submission, state + ' · código ' + code)
            return submission
        submission.state, submission.response_code, submission.message, submission.cdr_zip = state, code, message, cdr
        submission.save(update_fields=['state', 'response_code', 'message', 'cdr_zip'])
        audit(user, 'Resultado de factura beta', submission, state + ' · código ' + code)
    return submission

@transaction.atomic
def recover_interrupted(submission_id, user):
    from datetime import timedelta
    submission = BetaSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.state != 'ENVIANDO' or not submission.last_attempt_at or timezone.now() - submission.last_attempt_at < timedelta(minutes=3):
        raise ValidationError('Espera al menos tres minutos desde el inicio del envío antes de marcarlo como interrumpido.')
    submission.state = 'INCIERTO'
    submission.message = 'Envío interrumpido. Puede haber sido recibido por SUNAT; revisa antes de reintentar.'
    submission.save(update_fields=['state', 'message'])
    audit(user, 'Revisar envío beta interrumpido', submission)
    return submission
