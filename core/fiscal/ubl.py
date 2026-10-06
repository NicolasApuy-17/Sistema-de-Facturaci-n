"""Vista previa UBL 2.1 sin firma ni envío. No reserva numeración fiscal."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from django.core.exceptions import ValidationError
from lxml import etree

CBC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
CAC = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
NS = {'cbc': CBC, 'cac': CAC}
KINDS = {'FACTURA': ('Invoice', '01'), 'BOLETA': ('Invoice', '03'), 'CREDITO': ('CreditNote', '07'), 'DEBITO': ('DebitNote', '08')}
TAXES = {'10': ('1000', 'IGV', 'VAT', 'S', Decimal('18')), '20': ('9997', 'EXO', 'VAT', 'E', Decimal('0')), '30': ('9998', 'INA', 'FRE', 'O', Decimal('0'))}

def money(value): return format(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')
def child(parent, name, value=None, **attrs):
    prefix, tag = name.split(':')
    node = etree.SubElement(parent, '{' + NS[prefix] + '}' + tag, **attrs)
    if value is not None: node.text = str(value)
    return node

def preview_id(doc):
    original = doc.reference if doc.kind in ('CREDITO', 'DEBITO') else doc
    prefix = 'B' if original and original.kind == 'BOLETA' else 'F'
    return f'{prefix}PRV-{doc.pk}'

def validate_data(doc, company, lines):
    errors = []
    if not company or not company.name or not company.address or len(company.ruc) != 11 or not company.ruc.isdigit() or len(company.ubigeo) != 6 or not company.ubigeo.isdigit():
        errors.append('Completa razón social, RUC, dirección y ubigeo de la empresa en Configuración.')
    if doc.kind not in KINDS or doc.status == 'CANCELADO': errors.append('Este documento no admite vista previa XML.')
    if doc.customer_document_type not in ('DNI', 'RUC'):
        errors.append('La vista previa admite clientes con DNI o RUC; revisa el documento histórico.')
    else:
        size = 11 if doc.customer_document_type == 'RUC' else 8
        if not doc.customer_document.isdigit() or len(doc.customer_document) != size: errors.append('El documento del cliente es inválido.')
    original_kind = doc.reference.kind if doc.reference_id else doc.kind
    if original_kind == 'FACTURA' and doc.customer_document_type != 'RUC': errors.append('La factura o su nota requiere RUC del cliente.')
    if doc.kind in ('CREDITO', 'DEBITO'):
        allowed = ('01', '05', '07') if doc.kind == 'CREDITO' else ('01', '02')
        if not doc.reference_id or doc.note_code not in allowed or not doc.notes: errors.append('Revisa referencia y motivo de la nota.')
    if doc.due_date and doc.due_date > doc.date:
        errors.append('La vista previa al crédito requiere el próximo módulo de cuotas. No se representa como venta al contado.')
    if not lines or doc.total <= 0: errors.append('Agrega bienes con importe positivo.')
    for line in lines:
        if line.tax_category not in TAXES:
            errors.append(f'{line.description}: afectación al IGV pendiente en esta venta. Clasifica el producto antes de crear una venta nueva.')
        elif line.tax_rate != TAXES[line.tax_category][4]: errors.append(f'{line.description}: porcentaje y afectación al IGV no coinciden.')
        if line.package_use == 'PENDIENTE': errors.append(f'{line.description}: uso del producto pendiente en esta venta.')
        if line.package_use == 'TRANSPORTE': errors.append(f'{line.description}: falta implementar ICBPER para bolsas destinadas a llevar compras.')
        if line.package_use not in ('ALIMENTO', 'NO_APLICA', 'PENDIENTE', 'TRANSPORTE'): errors.append('Uso de producto no reconocido.')
        if line.quantity <= 0 or line.price <= 0: errors.append('Las transferencias gratuitas todavía no están implementadas en XML.')
        if money(line.quantity * line.price) != money(line.total) or line.subtotal + line.tax != line.total:
            errors.append('Los importes de una línea no concuerdan.')
    if sum((line.total for line in lines), Decimal(0)) != doc.total or sum((line.tax for line in lines), Decimal(0)) != doc.tax or sum((line.subtotal for line in lines), Decimal(0)) != doc.subtotal:
        errors.append('Los totales del documento no concuerdan con sus líneas.')
    if errors: raise ValidationError(errors)

def party(parent, role, name, number, document_type, address='', ubigeo=''):
    node = child(child(parent, 'cac:' + role), 'cac:Party')
    identification = child(node, 'cac:PartyIdentification')
    child(identification, 'cbc:ID', number, schemeID=document_type, schemeName='Documento de Identidad', schemeAgencyName='PE:SUNAT', schemeURI='urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06')
    legal = child(node, 'cac:PartyLegalEntity')
    child(legal, 'cbc:RegistrationName', name)
    if address:
        location = child(legal, 'cac:RegistrationAddress')
        if ubigeo: child(location, 'cbc:ID', ubigeo, schemeName='Ubigeos', schemeAgencyName='PE:INEI')
        if role == 'AccountingSupplierParty': child(location, 'cbc:AddressTypeCode', '0000')
        child(child(location, 'cac:AddressLine'), 'cbc:Line', address)
        child(child(location, 'cac:Country'), 'cbc:IdentificationCode', 'PE')

def tax_total(parent, total, groups, line=False):
    node = child(parent, 'cac:TaxTotal')
    child(node, 'cbc:TaxAmount', money(total), currencyID='PEN')
    for category, amounts in sorted(groups.items()):
        tax_id, name, tax_type, code, rate = TAXES[category]
        subtotal = child(node, 'cac:TaxSubtotal')
        child(subtotal, 'cbc:TaxableAmount', money(amounts[0]), currencyID='PEN')
        child(subtotal, 'cbc:TaxAmount', money(amounts[1]), currencyID='PEN')
        tax_category = child(subtotal, 'cac:TaxCategory')
        child(tax_category, 'cbc:ID', code, schemeID='UN/ECE 5305', schemeName='Tax Category Identifier', schemeAgencyName='United Nations Economic Commission for Europe')
        if line:
            child(tax_category, 'cbc:Percent', rate)
            child(tax_category, 'cbc:TaxExemptionReasonCode', category, listAgencyName='PE:SUNAT', listName='Afectacion del IGV', listURI='urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo07')
        scheme = child(tax_category, 'cac:TaxScheme')
        child(scheme, 'cbc:ID', tax_id)
        child(scheme, 'cbc:Name', name)
        child(scheme, 'cbc:TaxTypeCode', tax_type)

@lru_cache(maxsize=3)
def schema(root_name):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    path = Path(__file__).parent / 'schemas' / 'maindoc' / f'UBL-{root_name}-2.1.xsd'
    return etree.XMLSchema(etree.parse(str(path), parser))

def build_preview(doc, company):
    lines = list(doc.lines.order_by('pk'))
    validate_data(doc, company, lines)
    root_name, type_code = KINDS[doc.kind]
    root_ns = f'urn:oasis:names:specification:ubl:schema:xsd:{root_name}-2'
    root = etree.Element('{' + root_ns + '}' + root_name, nsmap={None: root_ns, **NS})
    child(root, 'cbc:UBLVersionID', '2.1')
    child(root, 'cbc:CustomizationID', '2.0')
    child(root, 'cbc:ID', preview_id(doc))
    child(root, 'cbc:IssueDate', doc.date.isoformat())
    if root_name == 'Invoice': child(root, 'cbc:InvoiceTypeCode', type_code, listID='0101', listAgencyName='PE:SUNAT', listName='Tipo de Documento', listURI='urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01')
    child(root, 'cbc:Note', 'PRUEBA SIN FIRMA NI VALIDEZ TRIBUTARIA. Numeración provisional, sin envío a SUNAT.')
    child(root, 'cbc:DocumentCurrencyCode', 'PEN')
    if doc.reference_id:
        response = child(root, 'cac:DiscrepancyResponse')
        child(response, 'cbc:ReferenceID', preview_id(doc.reference))
        child(response, 'cbc:ResponseCode', doc.note_code)
        child(response, 'cbc:Description', doc.notes)
        reference = child(child(root, 'cac:BillingReference'), 'cac:InvoiceDocumentReference')
        child(reference, 'cbc:ID', preview_id(doc.reference))
        child(reference, 'cbc:DocumentTypeCode', KINDS[doc.reference.kind][1])
    party(root, 'AccountingSupplierParty', company.name, company.ruc, '6', company.address, company.ubigeo)
    party(root, 'AccountingCustomerParty', doc.customer_name, doc.customer_document, '6' if doc.customer_document_type == 'RUC' else '1', doc.customer_address)
    if root_name == 'Invoice':
        payment = child(root, 'cac:PaymentTerms')
        child(payment, 'cbc:ID', 'FormaPago')
        child(payment, 'cbc:PaymentMeansID', 'Contado')
    groups = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for line in lines:
        groups[line.tax_category][0] += line.subtotal
        groups[line.tax_category][1] += line.tax
    tax_total(root, doc.tax, groups)
    monetary = child(root, 'cac:' + ('RequestedMonetaryTotal' if root_name == 'DebitNote' else 'LegalMonetaryTotal'))
    child(monetary, 'cbc:LineExtensionAmount', money(doc.subtotal), currencyID='PEN')
    child(monetary, 'cbc:TaxInclusiveAmount', money(doc.total), currencyID='PEN')
    child(monetary, 'cbc:PayableAmount', money(doc.total), currencyID='PEN')
    for index, line in enumerate(lines, 1):
        node = child(root, 'cac:' + root_name + 'Line')
        child(node, 'cbc:ID', index)
        quantity_tag = {'Invoice': 'InvoicedQuantity', 'CreditNote': 'CreditedQuantity', 'DebitNote': 'DebitedQuantity'}[root_name]
        child(node, 'cbc:' + quantity_tag, format(line.quantity, 'f'), unitCode=line.unit)
        child(node, 'cbc:LineExtensionAmount', money(line.subtotal), currencyID='PEN')
        price = child(child(node, 'cac:PricingReference'), 'cac:AlternativeConditionPrice')
        child(price, 'cbc:PriceAmount', money(line.price), currencyID='PEN')
        child(price, 'cbc:PriceTypeCode', '01')
        tax_total(node, line.tax, {line.tax_category: [line.subtotal, line.tax]}, line=True)
        item = child(node, 'cac:Item')
        child(item, 'cbc:Description', line.description)
        child(child(item, 'cac:SellersItemIdentification'), 'cbc:ID', line.sku)
        price = child(node, 'cac:Price')
        net_unit = line.price / (1 + line.tax_rate / 100)
        child(price, 'cbc:PriceAmount', format(net_unit.quantize(Decimal('.0000000001'), rounding=ROUND_HALF_UP), 'f'), currencyID='PEN')
    # Estructura comprobada con XSD estándar. No confundir con aceptación SUNAT.
    validator = schema(root_name)
    if not validator.validate(root):
        raise ValidationError('La estructura XML no pasó la validación UBL: ' + str(validator.error_log.last_error))
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=True)
