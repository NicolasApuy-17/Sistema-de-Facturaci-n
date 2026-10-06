import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from .forms import CustomerForm, GuideForm
from .models import AuditEvent, Customer, Document, Payment, Product, StockMovement
from .services import create_document, move_stock, register_payment, register_sale

class BusinessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('administrador', password='Test-only-strong-password', is_staff=True)
        self.customer = Customer.objects.create(name='Cliente de prueba', document_type='RUC', document='20123456789')
        self.product = Product.objects.create(sku='P001', name='Producto de prueba', price=Decimal('118'), minimum=1)
        self.client.force_login(self.user)

    def draft(self, qty='2', price='118'):
        return create_document({'kind': 'FACTURA', 'customer': self.customer, 'date': timezone.localdate(),
            'due_date': None, 'reference': None, 'notes': ''},
            [{'product': self.product, 'quantity': Decimal(qty), 'price': Decimal(price)}], self.user)

    def test_draft_preserves_stock_and_calculates_tax(self):
        doc = self.draft()
        self.assertEqual((doc.subtotal, doc.tax, doc.total), (Decimal('200'), Decimal('36'), Decimal('236')))
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(doc.sunat_status, 'NO_ENVIADO')

    def test_stock_entry_and_duplicate_request(self):
        key = uuid.uuid4()
        for _ in range(2): move_stock(self.product.pk, Decimal('10'), 'Entrada', self.user, key)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_negative_stock_rejected(self):
        with self.assertRaises(ValidationError): move_stock(self.product.pk, Decimal('-1'), 'Salida', self.user, uuid.uuid4())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_sale_is_atomic_and_repeat_safe(self):
        move_stock(self.product.pk, Decimal('10'), 'Entrada', self.user, uuid.uuid4())
        doc = self.draft()
        register_sale(doc.pk, self.user)
        register_sale(doc.pk, self.user)
        self.product.refresh_from_db()
        doc.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        self.assertEqual(doc.status, 'REGISTRADO')
        self.assertEqual(StockMovement.objects.filter(document=doc).count(), 1)
        self.assertEqual(doc.balance, 236)

    def test_insufficient_stock_rolls_back_all_products(self):
        move_stock(self.product.pk, Decimal('10'), 'Entrada', self.user, uuid.uuid4())
        second = Product.objects.create(sku='P002', name='Sin existencias', price=10)
        doc = create_document({'kind': 'BOLETA', 'customer': self.customer, 'date': timezone.localdate()}, [
            {'product': self.product, 'quantity': Decimal('2'), 'price': Decimal('118')},
            {'product': second, 'quantity': Decimal('1'), 'price': Decimal('10')}], self.user)
        with self.assertRaises(ValidationError): register_sale(doc.pk, self.user)
        self.product.refresh_from_db()
        doc.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertEqual(doc.status, 'BORRADOR')
        self.assertFalse(StockMovement.objects.filter(document=doc).exists())

    def test_duplicate_product_lines_combined_for_stock(self):
        move_stock(self.product.pk, Decimal('3'), 'Entrada', self.user, uuid.uuid4())
        doc = create_document({'kind': 'BOLETA', 'customer': self.customer, 'date': timezone.localdate()}, [
            {'product': self.product, 'quantity': Decimal('2'), 'price': Decimal('118')},
            {'product': self.product, 'quantity': Decimal('2'), 'price': Decimal('118')}], self.user)
        with self.assertRaises(ValidationError): register_sale(doc.pk, self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_partial_payment_duplicate_and_overpayment(self):
        move_stock(self.product.pk, Decimal('10'), 'Entrada', self.user, uuid.uuid4())
        doc = register_sale(self.draft().pk, self.user)
        data = {'amount': Decimal('100'), 'date': timezone.localdate(), 'method': 'EFECTIVO', 'reference': '', 'request_key': uuid.uuid4()}
        register_payment(doc.pk, data, self.user)
        register_payment(doc.pk, data, self.user)
        doc.refresh_from_db()
        self.assertEqual(doc.balance, 136)
        self.assertEqual(Payment.objects.count(), 1)
        with self.assertRaises(ValidationError): register_payment(doc.pk, {**data, 'amount': Decimal('137'), 'request_key': uuid.uuid4()}, self.user)
        doc.refresh_from_db()
        self.assertEqual(doc.paid, 100)

    def test_payment_on_draft_rejected(self):
        with self.assertRaises(ValidationError): register_payment(self.draft().pk,
            {'amount': Decimal('1'), 'date': timezone.localdate(), 'method': 'EFECTIVO', 'reference': '', 'request_key': uuid.uuid4()}, self.user)

    def test_notes_cannot_post_as_sales(self):
        doc = self.draft()
        doc.kind = 'CREDITO'
        doc.save()
        with self.assertRaises(ValidationError): register_sale(doc.pk, self.user)

    def test_login_required_and_nonadmins_denied(self):
        self.client.logout()
        for url in ['/', '/clientes/', '/inventario/', '/comprobantes/', '/guias/', '/configuracion/']:
            self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_user('noadmin', password='Test-only-strong-password')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/').status_code, 403)

    def test_pages_render_and_post_csrf_required(self):
        doc = self.draft()
        for url in ['/', '/clientes/', '/clientes/nuevo/', f'/clientes/{self.customer.pk}/cuenta/',
                    '/inventario/', '/inventario/producto/', '/inventario/movimiento/', '/comprobantes/',
                    '/comprobantes/nuevo/', f'/comprobantes/{doc.pk}/', '/guias/', '/guias/nueva/', '/configuracion/']:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code, 200)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(f'/comprobantes/{doc.pk}/registrar/').status_code, 403)
        self.assertEqual(self.client.get(f'/comprobantes/{doc.pk}/registrar/').status_code, 405)

    def test_customer_document_validation(self):
        form = CustomerForm({'name': 'Cliente', 'document_type': 'RUC', 'document': '123'})
        self.assertFalse(form.is_valid())
        self.assertIn('document', form.errors)

    def test_transporter_guide_validation(self):
        form = GuideForm({'kind': 'TRANSPORTISTA', 'customer': self.customer.pk,
            'transfer_date': timezone.localdate().isoformat(), 'reason': 'Venta', 'origin': 'Origen',
            'origin_ubigeo': '150101', 'destination': 'Destino', 'destination_ubigeo': '150102',
            'transport_mode': 'PUBLICO', 'weight': '12', 'goods': '2 unidades'})
        self.assertFalse(form.is_valid())
        for field in ['carrier_ruc', 'carrier_name', 'plate', 'driver_document', 'driver_license', 'related_gre']:
            self.assertIn(field, form.errors)

    def test_guide_draft_does_not_deduct_stock(self):
        before = StockMovement.objects.count()
        response = self.client.post('/guias/nueva/', {'kind': 'REMITENTE', 'customer': self.customer.pk,
            'transfer_date': timezone.localdate().isoformat(), 'reason': 'Venta', 'origin': 'Origen',
            'origin_ubigeo': '150101', 'destination': 'Destino', 'destination_ubigeo': '150102',
            'transport_mode': 'PRIVADO', 'weight': '12', 'goods': '2 unidades', 'plate': 'ABC-123',
            'driver_document': '12345678', 'driver_license': 'Q12345678',
            'goods-TOTAL_FORMS': '1', 'goods-INITIAL_FORMS': '0', 'goods-MIN_NUM_FORMS': '1', 'goods-MAX_NUM_FORMS': '100',
            'goods-0-product': self.product.pk, 'goods-0-quantity': '2'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.client.get(response.url).status_code, 200)

    def test_document_form_end_to_end(self):
        response = self.client.post('/comprobantes/nuevo/', {'kind': 'FACTURA', 'customer': self.customer.pk,
            'date': timezone.localdate().isoformat(), 'lines-TOTAL_FORMS': '1', 'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '1', 'lines-MAX_NUM_FORMS': '100', 'lines-0-product': self.product.pk,
            'lines-0-quantity': '2', 'lines-0-price': '118'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Document.objects.get().total, Decimal('236'))

class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('admin', is_staff=True)
        self.customer = Customer.objects.create(name='Cliente', document='20123456789')
        self.product = Product.objects.create(sku='STOCK', name='Última unidad', price=118)
        move_stock(self.product.pk, Decimal('1'), 'Inicial', self.user, uuid.uuid4())

    def test_two_sales_cannot_sell_same_last_unit(self):
        docs = [create_document({'kind': 'FACTURA', 'customer': self.customer, 'date': timezone.localdate()},
                [{'product': self.product, 'quantity': Decimal('1'), 'price': Decimal('118')}], self.user) for _ in range(2)]
        def worker(doc):
            close_old_connections()
            try:
                register_sale(doc.pk, self.user)
                return True
            except ValidationError: return False
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(worker, docs))
        self.assertEqual(sum(results), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)

    def test_concurrent_payments_cannot_overpay(self):
        doc = create_document({'kind': 'FACTURA', 'customer': self.customer, 'date': timezone.localdate()},
                [{'product': self.product, 'quantity': Decimal('1'), 'price': Decimal('118')}], self.user)
        register_sale(doc.pk, self.user)
        def worker(index):
            close_old_connections()
            try:
                register_payment(doc.pk, {'amount': Decimal('100'), 'date': timezone.localdate(),
                    'method': 'EFECTIVO', 'reference': '', 'request_key': uuid.uuid4()}, self.user)
                return True
            except ValidationError: return False
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(worker, range(2)))
        self.assertEqual(sum(results), 1)
        doc.refresh_from_db()
        self.assertEqual(doc.paid, 100)
