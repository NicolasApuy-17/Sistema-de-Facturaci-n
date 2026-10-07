import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.db import models

POS = MinValueValidator(Decimal('0.001'))
MONEY = MinValueValidator(Decimal('0.01'))
TAX_CATEGORIES = [('10', 'Gravado — IGV 18%'), ('20', 'Exonerado — IGV 0%'), ('30', 'Inafecto — IGV 0%'), ('PENDIENTE', 'Pendiente de clasificación')]
PACKAGE_USES = [('ALIMENTO', 'Envase para alimentos a granel / inocuidad'), ('NO_APLICA', 'Otro producto: no es bolsa para llevar compras'), ('TRANSPORTE', 'Bolsa para cargar o llevar compras'), ('PENDIENTE', 'Pendiente de clasificar')]

class Customer(models.Model):
    TYPES = [('RUC', 'RUC'), ('DNI', 'DNI'), ('OTRO', 'Otro documento')]
    name = models.CharField('Nombre o razón social', max_length=200)
    document_type = models.CharField('Tipo de documento', max_length=4, choices=TYPES, default='RUC')
    document = models.CharField('Número de documento', max_length=20, unique=True)
    address = models.CharField('Dirección', max_length=250, blank=True)
    phone = models.CharField('Teléfono', max_length=30, blank=True)
    email = models.EmailField('Correo electrónico', blank=True)
    class Meta:
        ordering = ['name']
    def __str__(self): return f'{self.name} · {self.document}'

class Product(models.Model):
    sku = models.CharField('Código', max_length=40, unique=True)
    name = models.CharField('Producto', max_length=200)
    unit = models.CharField('Unidad', max_length=3, default='NIU', choices=[('NIU', 'Unidad'), ('KGM', 'Kilogramo'), ('MTR', 'Metro'), ('LTR', 'Litro')])
    price = models.DecimalField('Precio de venta con impuesto (S/)', max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    tax_rate = models.DecimalField('IGV (%)', max_digits=5, decimal_places=2, default=18, choices=[(Decimal('18'), '18%'), (Decimal('0'), '0% — pendiente de clasificar tributariamente')])
    tax_category = models.CharField('Afectación al IGV', max_length=9, choices=TAX_CATEGORIES, default='10')
    package_use = models.CharField('Uso del producto / bolsa', max_length=10, choices=PACKAGE_USES, default='PENDIENTE', help_text='Clasifica el uso real. Envase alimenticio no implica IGV 0%. Las bolsas para llevar compras requieren tratamiento ICBPER, aún pendiente.')
    stock = models.DecimalField(max_digits=16, decimal_places=3, default=0, editable=False)
    minimum = models.DecimalField('Stock mínimo', max_digits=16, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    active = models.BooleanField('Disponible para nuevas ventas', default=True)
    version = models.PositiveIntegerField(default=1, editable=False)
    class Meta:
        ordering = ['name']
        constraints = [models.CheckConstraint(condition=models.Q(stock__gte=0), name='stock_nonnegative')]
    def __str__(self): return f'{self.sku} · {self.name}'
    def clean(self):
        expected = {'10': Decimal('18'), '20': Decimal('0'), '30': Decimal('0')}.get(self.tax_category)
        if expected is not None and self.tax_rate != expected:
            raise ValidationError({'tax_category': 'La afectación al IGV no coincide con el porcentaje del producto.'})

class Document(models.Model):
    TYPES = [('FACTURA', 'Factura'), ('BOLETA', 'Boleta'), ('CREDITO', 'Nota de crédito'), ('DEBITO', 'Nota de débito')]
    kind = models.CharField('Tipo', max_length=10, choices=TYPES)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, verbose_name='Cliente', related_name='documents')
    reference = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, verbose_name='Venta relacionada')
    customer_name = models.CharField(max_length=200)
    customer_document = models.CharField(max_length=20)
    customer_document_type = models.CharField(max_length=4, blank=True)
    customer_address = models.CharField(max_length=250, blank=True)
    date = models.DateField('Fecha')
    due_date = models.DateField('Vencimiento', null=True, blank=True)
    status = models.CharField(max_length=12, choices=[('BORRADOR', 'Borrador'), ('REGISTRADO', 'Operación interna registrada'), ('CANCELADO', 'Borrador cancelado')], default='BORRADOR')
    sunat_status = models.CharField(max_length=15, default='NO_ENVIADO', editable=False)
    subtotal = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    paid = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)
    credited = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)
    debited = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)
    refunded = models.DecimalField(max_digits=16, decimal_places=2, default=0, editable=False)
    note_code = models.CharField('Motivo de la nota', max_length=2, blank=True, choices=[('01', 'Anulación / interés por mora (según tipo)'), ('02', 'Aumento de valor (débito)'), ('05', 'Descuento por ítem (crédito)'), ('07', 'Devolución por ítem (crédito)')])
    return_stock = models.BooleanField('La mercadería se recibió físicamente de vuelta', default=False)
    notes = models.TextField('Observaciones / motivo de la nota', blank=True, max_length=1000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']
        constraints = [models.CheckConstraint(condition=models.Q(paid__gte=0) & models.Q(credited__gte=0) & models.Q(debited__gte=0) & models.Q(refunded__gte=0) & models.Q(refunded__lte=models.F('paid')), name='document_amounts_nonnegative')]
    @property
    def balance(self): return self.total + self.debited - self.credited - self.paid + self.refunded
    @property
    def amount_due(self): return max(self.balance, Decimal('0'))
    @property
    def available_credit(self): return max(-self.balance, Decimal('0'))
    @property
    def code(self): return f'INT-{self.pk:06d}'
    def __str__(self): return f'{self.code} · {self.customer_name}'

class DocumentLine(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    unit = models.CharField(max_length=3)
    sku = models.CharField(max_length=40, blank=True)
    source_line = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='adjustments', verbose_name='Línea de la venta original')
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[POS])
    price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    tax_category = models.CharField(max_length=9, choices=TAX_CATEGORIES, default='PENDIENTE')
    package_use = models.CharField(max_length=10, choices=PACKAGE_USES, default='PENDIENTE')
    subtotal = models.DecimalField(max_digits=16, decimal_places=2)
    tax = models.DecimalField(max_digits=16, decimal_places=2)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    def __str__(self): return f'{self.document.code} · {self.description} · {self.quantity} {self.unit}'

class StockMovement(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_name = models.CharField(max_length=200, blank=True)
    product_sku = models.CharField(max_length=40, blank=True)
    product_unit = models.CharField(max_length=3, blank=True)
    quantity = models.DecimalField(max_digits=16, decimal_places=3)
    balance = models.DecimalField(max_digits=16, decimal_places=3)
    reason = models.CharField(max_length=250)
    document = models.ForeignKey(Document, null=True, on_delete=models.PROTECT)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']
        constraints = [models.CheckConstraint(condition=~models.Q(quantity=0), name='movement_nonzero')]

class Payment(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField('Importe (S/)', max_digits=16, decimal_places=2, validators=[MONEY])
    date = models.DateField('Fecha')
    method = models.CharField('Medio de pago', max_length=15, choices=[('EFECTIVO', 'Efectivo'), ('TRANSFERENCIA', 'Transferencia'), ('YAPE', 'Yape / Plin'), ('TARJETA', 'Tarjeta')])
    reference = models.CharField('Referencia / número de operación', max_length=100, blank=True)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='payment_positive')]

class Guide(models.Model):
    kind = models.CharField('Tipo de guía', max_length=15, choices=[('REMITENTE', 'Remisión remitente'), ('TRANSPORTISTA', 'Remisión transportista')])
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, verbose_name='Destinatario')
    sale = models.ForeignKey(Document, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Venta interna relacionada')
    transfer_date = models.DateField('Inicio del traslado')
    reason = models.CharField('Motivo del traslado', max_length=100)
    origin = models.CharField('Dirección de partida', max_length=250)
    origin_ubigeo = models.CharField('Ubigeo de partida', max_length=6, validators=[RegexValidator(r'^\d{6}$', 'Ingresa un ubigeo de 6 dígitos.')])
    destination = models.CharField('Dirección de llegada', max_length=250)
    destination_ubigeo = models.CharField('Ubigeo de llegada', max_length=6, validators=[RegexValidator(r'^\d{6}$', 'Ingresa un ubigeo de 6 dígitos.')])
    transport_mode = models.CharField('Modalidad', max_length=7, choices=[('PUBLICO', 'Público'), ('PRIVADO', 'Privado')])
    carrier_ruc = models.CharField('RUC del transportista', max_length=11, blank=True)
    carrier_name = models.CharField('Razón social del transportista', max_length=200, blank=True)
    plate = models.CharField('Placa del vehículo', max_length=15, blank=True)
    driver_document = models.CharField('Documento del conductor', max_length=20, blank=True)
    driver_license = models.CharField('Licencia del conductor', max_length=25, blank=True)
    related_gre = models.CharField('GRE remitente relacionada (serie-número)', max_length=30, blank=True)
    weight = models.DecimalField('Peso bruto total (kg)', max_digits=14, decimal_places=3, validators=[POS])
    goods = models.TextField('Observaciones de bienes (registros anteriores)', max_length=3000, blank=True)
    status = models.CharField(max_length=15, default='BORRADOR', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']

class GuideLine(models.Model):
    guide = models.ForeignKey(Guide, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    sku = models.CharField(max_length=40)
    description = models.CharField(max_length=200)
    unit = models.CharField(max_length=3)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[POS])

class Refund(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name='refunds')
    amount = models.DecimalField('Importe a devolver (S/)', max_digits=16, decimal_places=2, validators=[MONEY])
    date = models.DateField('Fecha')
    method = models.CharField('Medio de devolución', max_length=15, choices=Payment._meta.get_field('method').choices)
    reference = models.CharField('Número de operación / motivo', max_length=200)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='refund_positive')]

class Company(models.Model):
    name = models.CharField('Razón social', max_length=200)
    ruc = models.CharField('RUC', max_length=11, blank=True)
    address = models.CharField('Dirección fiscal', max_length=250, blank=True)
    ubigeo = models.CharField('Ubigeo', max_length=6, blank=True)
    regime = models.CharField('Régimen tributario', max_length=30, blank=True, choices=[('RER', 'Régimen especial'), ('MYPE', 'Régimen MYPE tributario'), ('GENERAL', 'Régimen general'), ('RUS', 'Nuevo RUS')])
    ose_required = models.BooleanField('Obligado a usar OSE', default=False)

class AuditEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=30)
    object_id = models.PositiveBigIntegerField()
    detail = models.TextField(max_length=5000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']

class BetaSubmission(models.Model):
    STATES = [('PREPARADO', 'Firmado para pruebas'), ('ENVIANDO', 'Enviando a beta'), ('ACEPTADO', 'Aceptado en beta'), ('RECHAZADO', 'Rechazado en beta'), ('ERROR', 'Error de servicio'), ('INCIERTO', 'Respuesta pendiente de comprobar')]
    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name='beta_submission')
    ruc = models.CharField(max_length=11)
    filename = models.CharField(max_length=70)
    signed_xml = models.BinaryField()
    payload_zip = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    demo_certificate = models.BooleanField(default=True)
    certificate_fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=12, choices=STATES, default='PREPARADO')
    attempts = models.PositiveIntegerField(default=0)
    response_code = models.CharField(max_length=30, blank=True)
    message = models.CharField(max_length=1000, blank=True)
    cdr_zip = models.BinaryField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True)
