from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from .models import AuditEvent, Document, DocumentLine, Guide, GuideLine, Payment, Product, Refund, StockMovement

def cents(value): return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def audit(user, action, obj, detail=''):
    AuditEvent.objects.create(user=user, action=action, object_type=obj.__class__.__name__, object_id=obj.pk, detail=detail)

@transaction.atomic
def edit_product(product_id, data, expected_version, user):
    import json
    product = Product.objects.select_for_update().get(pk=product_id)
    if product.version != expected_version:
        raise ValidationError('Otro administrador modificó este producto. Vuelve a abrirlo para revisar los datos actuales.')
    if data['unit'] != product.unit and (product.stock != 0 or product.stockmovement_set.exists() or product.documentline_set.exists() or product.guideline_set.exists()):
        raise ValidationError('La unidad no puede cambiar cuando hay stock o historial. Crea un producto con la nueva unidad.')
    changes = {}
    for name in ['sku', 'name', 'unit', 'price', 'tax_rate', 'tax_category', 'package_use', 'minimum', 'active']:
        if name not in data: continue
        if getattr(product, name) != data[name]:
            changes[name] = {'antes': str(getattr(product, name)), 'después': str(data[name])}
            setattr(product, name, data[name])
    if changes:
        product.version += 1
        product.full_clean()
        product.save(update_fields=[*changes, 'version'])
        audit(user, 'Editar producto', product, json.dumps(changes, ensure_ascii=False))
    return product

@transaction.atomic
def create_document(data, rows, user):
    data = dict(data)
    if not rows: raise ValidationError('Agrega al menos una línea.')
    is_note = data['kind'] in ('CREDITO', 'DEBITO')
    reference = data.get('reference')
    if reference:
        reference = Document.objects.select_for_update().get(pk=reference.pk)
        data['reference'] = reference
    if is_note and (not reference or reference.status != 'REGISTRADO' or reference.kind not in ('FACTURA', 'BOLETA') or reference.customer_id != data['customer'].pk):
        raise ValidationError('La nota debe corresponder a una venta registrada del mismo cliente.')
    if is_note and not data.get('note_code'): raise ValidationError('Selecciona el motivo de la nota.')
    doc = Document(**data, created_by=user, customer_name=data['customer'].name,
                   customer_document=data['customer'].document,
                   customer_document_type=data['customer'].document_type, customer_address=data['customer'].address)
    doc.save()
    for row in rows:
        product = Product.objects.get(pk=row['product'].pk)
        source = row.get('source_line')
        if source: source = DocumentLine.objects.get(pk=source.pk)
        if row['quantity'] <= 0 or row['price'] < 0: raise ValidationError('Revisa cantidad y precio de las líneas.')
        if is_note:
            if not source or source.document_id != reference.pk or source.product_id != product.pk:
                raise ValidationError('Cada línea de una nota debe identificar la línea de la venta original.')
            description, unit, sku, rate = source.description, source.unit, source.sku, source.tax_rate
            category, package_use = source.tax_category, source.package_use
        else:
            if not product.active: raise ValidationError(f'{product.name} está desactivado para nuevas ventas.')
            description, unit, sku, rate = product.name, product.unit, product.sku, product.tax_rate
            category, package_use = product.tax_category, product.package_use
            if source: raise ValidationError('Una venta nueva no debe tener líneas de origen.')
        total = cents(row['quantity'] * row['price'])
        if total > Decimal('99999999999999.99'): raise ValidationError('El importe excede el límite permitido.')
        subtotal = cents(total / (1 + rate / 100))
        DocumentLine.objects.create(document=doc, product=product, description=description, unit=unit, sku=sku, source_line=source,
            quantity=row['quantity'], price=row['price'], tax_rate=rate, tax_category=category, package_use=package_use,
            subtotal=subtotal, tax=total-subtotal, total=total)
        doc.subtotal += subtotal
        doc.tax += total - subtotal
        doc.total += total
    if doc.total <= 0 or doc.total > Decimal('99999999999999.99'):
        raise ValidationError('El documento debe tener un importe total mayor a cero.')
    doc.save(update_fields=['subtotal', 'tax', 'total'])
    audit(user, 'Crear borrador', doc)
    return doc

@transaction.atomic
def move_stock(product_id, delta, reason, user, key):
    product = Product.objects.select_for_update().get(pk=product_id)
    prior = StockMovement.objects.filter(request_key=key).first()
    if prior:
        if prior.product_id != product_id or prior.quantity != delta or prior.reason != reason:
            raise ValidationError('La solicitud ya se utilizó para un movimiento diferente.')
        return prior
    if delta == 0 or product.stock + delta < 0:
        raise ValidationError('El movimiento dejaría stock negativo o no modifica existencias.')
    product.stock += delta
    product.save(update_fields=['stock'])
    movement = StockMovement.objects.create(product=product, quantity=delta, balance=product.stock,
        reason=reason, created_by=user, request_key=key, product_name=product.name, product_sku=product.sku, product_unit=product.unit)
    audit(user, 'Registrar movimiento', movement)
    return movement

@transaction.atomic
def register_sale(doc_id, user):
    doc = Document.objects.select_for_update().get(pk=doc_id)
    if doc.status == 'REGISTRADO': return doc
    if doc.status != 'BORRADOR': raise ValidationError('El documento está cancelado.')
    if doc.kind not in ('FACTURA', 'BOLETA'):
        raise ValidationError('Las notas permanecen como borradores hasta implementar su aplicación tributaria y contable.')
    quantities = defaultdict(Decimal)
    for line in doc.lines.all(): quantities[line.product_id] += line.quantity
    products = list(Product.objects.select_for_update().filter(pk__in=quantities).order_by('pk'))
    for product in products:
        if not product.active: raise ValidationError(f'{product.name} está desactivado. Revisa la venta antes de registrarla.')
        if product.stock < quantities[product.pk]:
            raise ValidationError(f'Stock insuficiente para {product.name}. Disponible: {product.stock}.')
    for product in products:
        product.stock -= quantities[product.pk]
        product.save(update_fields=['stock'])
        StockMovement.objects.create(product=product, quantity=-quantities[product.pk], balance=product.stock,
            reason=f'Venta interna {doc.code}', document=doc, created_by=user,
            product_name=product.name, product_sku=product.sku, product_unit=product.unit)
    doc.status = 'REGISTRADO'
    doc.save(update_fields=['status'])
    audit(user, 'Registrar venta interna', doc)
    return doc

@transaction.atomic
def register_payment(doc_id, data, user):
    doc = Document.objects.select_for_update().get(pk=doc_id)
    prior = Payment.objects.filter(request_key=data['request_key']).first()
    if prior:
        if prior.document_id != doc.pk or prior.amount != data['amount']:
            raise ValidationError('La solicitud ya se utilizó para un pago diferente.')
        return prior
    if doc.status != 'REGISTRADO' or doc.kind not in ('FACTURA', 'BOLETA'):
        raise ValidationError('Solo puedes cobrar ventas internas registradas.')
    if data['amount'] <= 0 or data['amount'] > doc.balance:
        raise ValidationError('El pago debe ser positivo y no puede superar el saldo pendiente.')
    payment = Payment.objects.create(document=doc, created_by=user, **data)
    doc.paid += payment.amount
    doc.save(update_fields=['paid'])
    audit(user, 'Registrar pago', payment)
    return payment

@transaction.atomic
def register_note(doc_id, user):
    reference_id = Document.objects.get(pk=doc_id).reference_id
    if not reference_id: raise ValidationError('La nota no tiene una venta relacionada.')
    # Todas las notas y cobros de una venta comparten el mismo bloqueo.
    original = Document.objects.select_for_update().get(pk=reference_id)
    doc = Document.objects.select_for_update().get(pk=doc_id)
    if doc.status == 'REGISTRADO': return doc
    if doc.status != 'BORRADOR' or doc.kind not in ('CREDITO', 'DEBITO'):
        raise ValidationError('No es un borrador de nota válido.')
    if original.status != 'REGISTRADO' or original.kind not in ('FACTURA', 'BOLETA') or original.customer_id != doc.customer_id:
        raise ValidationError('Revisa la venta de origen de la nota.')
    if doc.kind == 'DEBITO':
        if doc.note_code not in ('01', '02') or doc.return_stock: raise ValidationError('Selecciona interés por mora o aumento de valor. Una nota de débito no retorna mercadería.')
        original.debited += doc.total
    else:
        if doc.note_code not in ('01', '05', '07'): raise ValidationError('Selecciona anulación, descuento por ítem o devolución por ítem.')
        if doc.total > original.total - original.credited:
            raise ValidationError('El crédito acumulado no puede superar el importe de la venta original.')
        if doc.note_code == '01' and doc.total != original.total - original.credited:
            raise ValidationError('Para anular, la nota debe cubrir todo el importe restante de la venta.')
        if doc.return_stock and doc.note_code == '05': raise ValidationError('Un descuento de precio no retorna mercadería.')
        quantities = defaultdict(Decimal)
        amounts = defaultdict(Decimal)
        source_rows = {}
        for line in doc.lines.select_related('source_line'):
            source = line.source_line
            if not source or source.document_id != original.pk or source.product_id != line.product_id:
                raise ValidationError('Revisa las líneas de la venta original.')
            quantities[source.pk] += line.quantity
            amounts[source.pk] += line.total
            source_rows[source.pk] = source
        for source_id, source in source_rows.items():
            used = source.adjustments.filter(document__kind='CREDITO', document__status='REGISTRADO').aggregate(n=Sum('total'))['n'] or Decimal('0')
            if amounts[source_id] > source.total - used: raise ValidationError(f'El crédito supera el importe disponible para {source.description}.')
            if doc.return_stock:
                returned = source.adjustments.filter(document__kind='CREDITO', document__status='REGISTRADO', document__return_stock=True).aggregate(n=Sum('quantity'))['n'] or Decimal('0')
                if quantities[source_id] > source.quantity - returned: raise ValidationError(f'La devolución supera las unidades vendidas de {source.description}.')
        if doc.return_stock:
            product_quantities = defaultdict(Decimal)
            for source_id, quantity in quantities.items(): product_quantities[source_rows[source_id].product_id] += quantity
            for product in Product.objects.select_for_update().filter(pk__in=product_quantities).order_by('pk'):
                product.stock += product_quantities[product.pk]
                product.save(update_fields=['stock'])
                source = next(row for row in source_rows.values() if row.product_id == product.pk)
                StockMovement.objects.create(product=product, quantity=product_quantities[product.pk], balance=product.stock,
                    reason=f'Devolución interna {doc.code}', document=doc, created_by=user,
                    product_name=source.description, product_sku=source.sku, product_unit=source.unit)
        original.credited += doc.total
    original.full_clean()
    original.save(update_fields=['credited', 'debited'])
    doc.status = 'REGISTRADO'
    doc.save(update_fields=['status'])
    audit(user, 'Aplicar nota interna', doc)
    return doc

@transaction.atomic
def register_refund(doc_id, data, user):
    doc = Document.objects.select_for_update().get(pk=doc_id)
    previous = Refund.objects.filter(request_key=data['request_key']).first()
    if previous:
        if previous.document_id != doc.pk or previous.amount != data['amount']: raise ValidationError('La solicitud corresponde a otra devolución.')
        return previous
    if doc.kind not in ('FACTURA', 'BOLETA') or doc.status != 'REGISTRADO' or data['amount'] <= 0 or data['amount'] > doc.available_credit:
        raise ValidationError('La devolución no puede superar el saldo a favor del cliente en esta venta.')
    refund = Refund.objects.create(document=doc, created_by=user, **data)
    doc.refunded += refund.amount
    doc.save(update_fields=['refunded'])
    audit(user, 'Devolver dinero', refund)
    return refund

@transaction.atomic
def create_guide(data, rows, user):
    if not rows: raise ValidationError('Agrega al menos un bien a trasladar.')
    guide = Guide(**data, created_by=user)
    guide.full_clean()
    guide.save()
    for row in rows:
        product = Product.objects.get(pk=row['product'].pk)
        if row['quantity'] <= 0: raise ValidationError('La cantidad debe ser positiva.')
        GuideLine.objects.create(guide=guide, product=product, sku=product.sku, description=product.name, unit=product.unit, quantity=row['quantity'])
    audit(user, 'Crear borrador de guía', guide)
    return guide

@transaction.atomic
def cancel_draft(doc_id, user):
    doc = Document.objects.select_for_update().get(pk=doc_id)
    if doc.status == 'CANCELADO': return doc
    if doc.status != 'BORRADOR': raise ValidationError('Una operación registrada se corrige mediante notas; no se elimina ni cancela directamente.')
    doc.status = 'CANCELADO'
    doc.save(update_fields=['status'])
    audit(user, 'Cancelar borrador', doc)
    return doc
