"""Datos sintéticos únicamente bajo demo_settings; nunca sobre la base real."""
from decimal import Decimal
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.demo_settings': raise RuntimeError('Solo se puede preparar la demo aislada.')
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from core.models import Company, Customer, Product
from core.services import create_document, move_stock, register_payment, register_sale

if settings.DATABASES['default']['NAME'] != 'facturacion_demo': raise RuntimeError('Base de demo incorrecta.')

@transaction.atomic
def seed():
    if get_user_model().objects.filter(username='demo').exists(): return
    user = get_user_model().objects.create_user('demo', password='PruebaEmpresa-2026!', is_staff=True)
    Company.objects.create(name='EMPRESA FICTICIA PARA DEMOSTRACION', ruc='20100066603', address='DIRECCION FICTICIA DE PRUEBA', ubigeo='150101', regime='GENERAL')
    customer = Customer.objects.create(name='CLIENTE FICTICIO CON RUC', document_type='RUC', document='20100066603', address='DIRECCION FICTICIA')
    Customer.objects.create(name='CLIENTE FICTICIO CON DNI', document_type='DNI', document='87654321', address='DIRECCION FICTICIA')
    products = []
    for sku, name, price, use in [('BOL-001', 'Bolsa alimenticia para arroz (prueba)', '1.18', 'ALIMENTO'),
        ('BOL-002', 'Bolsa alimenticia pequeña (prueba)', '0.59', 'ALIMENTO'),
        ('CAJ-001', 'Caja de plástico (prueba)', '11.80', 'NO_APLICA')]:
        product = Product.objects.create(sku=sku, name=name, price=Decimal(price), minimum=20, package_use=use)
        move_stock(product.pk, Decimal('200'), 'Existencias ficticias de demostración', user, uuid.uuid4())
        products.append(product)
    doc = create_document({'kind': 'FACTURA', 'customer': customer, 'date': timezone.localdate()},
        [{'product': products[0], 'quantity': Decimal('10'), 'price': products[0].price}], user)
    register_sale(doc.pk, user)
    register_payment(doc.pk, {'date': timezone.localdate(), 'amount': Decimal('5.00'), 'method': 'EFECTIVO', 'reference': 'Pago ficticio', 'request_key': uuid.uuid4()}, user)
    create_document({'kind': 'FACTURA', 'customer': customer, 'date': timezone.localdate()},
        [{'product': products[2], 'quantity': Decimal('2'), 'price': products[2].price}], user)

if __name__ == '__main__': seed()
