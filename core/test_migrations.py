from decimal import Decimal
import uuid
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

class UpgradeTests(TransactionTestCase):
    def test_upgrade_preserves_legacy_products_sales_and_movements(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('core', '0001_initial')])
        try:
            old = executor.loader.project_state([('core', '0001_initial')]).apps
            user = get_user_model().objects.create_user('usuario_anterior', is_staff=True)
            customer = old.get_model('core', 'Customer').objects.create(name='Cliente anterior', document='20123456789')
            product = old.get_model('core', 'Product').objects.create(sku='COD-ANTERIOR', name='Producto anterior', unit='NIU', price=118, stock=8)
            zero_product = old.get_model('core', 'Product').objects.create(sku='CERO-ANTERIOR', name='Producto con 0% anterior', price=10, tax_rate=0)
            document = old.get_model('core', 'Document').objects.create(kind='FACTURA', customer_id=customer.pk,
                customer_name=customer.name, customer_document=customer.document, date=timezone.localdate(),
                status='REGISTRADO', subtotal=200, tax=36, total=236, paid=100, created_by_id=user.pk)
            line = old.get_model('core', 'DocumentLine').objects.create(document_id=document.pk, product_id=product.pk,
                description='Descripción histórica de venta', unit='NIU', quantity=2, price=118, tax_rate=18, subtotal=200, tax=36, total=236)
            movement = old.get_model('core', 'StockMovement').objects.create(product_id=product.pk, quantity=-2, balance=8,
                reason='Venta anterior', document_id=document.pk, created_by_id=user.pk, request_key=uuid.uuid4())
            executor = MigrationExecutor(connection)
            executor.migrate([('core', '0005_tax_classification')])
            from .models import Document, DocumentLine, Product, StockMovement
            migrated = Product.objects.get(pk=product.pk)
            self.assertEqual(migrated.stock, Decimal('8'))
            self.assertTrue(migrated.active)
            zero_migrated = Product.objects.get(pk=zero_product.pk)
            self.assertEqual(zero_migrated.tax_rate, 0)
            self.assertEqual(zero_migrated.tax_category, 'PENDIENTE')
            self.assertEqual(StockMovement.objects.get(pk=movement.pk).product_name, 'Producto anterior')
            self.assertEqual(StockMovement.objects.get(pk=movement.pk).product_sku, 'COD-ANTERIOR')
            self.assertEqual(DocumentLine.objects.get(pk=line.pk).description, 'Descripción histórica de venta')
            self.assertEqual(DocumentLine.objects.get(pk=line.pk).sku, 'COD-ANTERIOR')
            self.assertEqual(Document.objects.get(pk=document.pk).balance, Decimal('136'))
            self.assertEqual(DocumentLine.objects.get(pk=line.pk).tax_category, '10')
            self.assertEqual(DocumentLine.objects.get(pk=line.pk).package_use, 'PENDIENTE')
        finally:
            MigrationExecutor(connection).migrate([('core', '0005_tax_classification')])
