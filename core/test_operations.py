import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from .models import AuditEvent, Customer, Document, GuideLine, Product, Refund, StockMovement
from .services import cancel_draft, create_document, edit_product, move_stock, register_note, register_payment, register_refund, register_sale

class OperationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('operador', password='Seguro-Prueba-4791!', is_staff=True)
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Cliente', document='20123456789')
        self.product = Product.objects.create(sku='ORIGINAL', name='Nombre original', price=118)
        move_stock(self.product.pk, Decimal('10'), 'Entrada inicial', self.user, uuid.uuid4())
        self.sale = create_document({'kind': 'FACTURA', 'customer': self.customer, 'date': timezone.localdate()},
            [{'product': self.product, 'quantity': Decimal('2'), 'price': Decimal('118')}], self.user)
        register_sale(self.sale.pk, self.user)
        self.source = self.sale.lines.get()

    def product_data(self, **overrides):
        return {**{name: getattr(self.product, name) for name in ['sku', 'name', 'unit', 'price', 'tax_rate', 'tax_category', 'package_use', 'minimum', 'active']}, **overrides}

    def note(self, amount='118', quantity='1', kind='CREDITO', code='07', stock=False):
        return create_document({'kind': kind, 'customer': self.customer, 'reference': self.sale,
            'date': timezone.localdate(), 'note_code': code, 'return_stock': stock, 'notes': 'Corrección de prueba'},
            [{'product': self.product, 'quantity': Decimal(quantity), 'price': Decimal(amount), 'source_line': self.source}], self.user)

    def pay(self, amount):
        return register_payment(self.sale.pk, {'amount': Decimal(amount), 'date': timezone.localdate(), 'method': 'EFECTIVO',
            'reference': '', 'request_key': uuid.uuid4()}, self.user)

    def test_edit_product_keeps_stock_sale_and_movement_snapshots(self):
        updated = edit_product(self.product.pk, self.product_data(name='Nombre nuevo', sku='NUEVO', price=Decimal('200')), 1, self.user)
        self.source.refresh_from_db()
        self.assertEqual(updated.stock, 8)
        self.assertEqual(updated.version, 2)
        self.assertEqual(self.source.description, 'Nombre original')
        self.assertEqual(self.source.sku, 'ORIGINAL')
        self.assertEqual(self.source.price, Decimal('118'))
        self.assertEqual(StockMovement.objects.first().product_name, 'Nombre original')
        self.assertIn('Nombre original', AuditEvent.objects.filter(action='Editar producto').get().detail)

    def test_edit_cannot_modify_unit_with_history(self):
        with self.assertRaises(ValidationError): edit_product(self.product.pk, self.product_data(unit='KGM'), 1, self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.unit, 'NIU')

    def test_stale_edit_rejected(self):
        edit_product(self.product.pk, self.product_data(name='Cambio 1'), 1, self.user)
        with self.assertRaises(ValidationError): edit_product(self.product.pk, self.product_data(name='Cambio 2'), 1, self.user)

    def test_edit_route_and_audit(self):
        self.assertEqual(self.client.get(f'/inventario/{self.product.pk}/editar/').status_code, 200)
        response = self.client.post(f'/inventario/{self.product.pk}/editar/', {**self.product_data(), 'name': 'Editado desde pantalla', 'expected_version': 1})
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Editado desde pantalla')
        self.assertEqual(self.product.stock, 8)

    def test_inactive_product_not_used_in_new_sales(self):
        edit_product(self.product.pk, self.product_data(active=False), 1, self.user)
        with self.assertRaises(ValidationError): create_document({'kind': 'BOLETA', 'customer': self.customer, 'date': timezone.localdate()},
            [{'product': self.product, 'quantity': Decimal('1'), 'price': Decimal('118')}], self.user)

    def test_return_note_updates_balance_and_stock_only_once(self):
        note = self.note(stock=True)
        register_note(note.pk, self.user)
        register_note(note.pk, self.user)
        self.sale.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.sale.credited, 118)
        self.assertEqual(self.sale.balance, 118)
        self.assertEqual(self.product.stock, 9)
        self.assertEqual(StockMovement.objects.filter(document=note).count(), 1)

    def test_discount_does_not_return_stock(self):
        register_note(self.note(amount='20', code='05').pk, self.user)
        self.product.refresh_from_db(); self.sale.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        self.assertEqual(self.sale.balance, 216)

    def test_discount_cannot_return_stock(self):
        with self.assertRaises(ValidationError): register_note(self.note(amount='20', code='05', stock=True).pk, self.user)

    def test_credit_cannot_exceed_original_amount(self):
        with self.assertRaises(ValidationError): register_note(self.note(amount='237').pk, self.user)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.credited, 0)

    def test_return_cannot_exceed_sold_quantity_even_with_low_price(self):
        with self.assertRaises(ValidationError): register_note(self.note(amount='1', quantity='3', stock=True).pk, self.user)

    def test_total_cancel_requires_full_remaining_amount(self):
        with self.assertRaises(ValidationError): register_note(self.note(amount='118', code='01').pk, self.user)
        register_note(self.note(amount='118', quantity='2', code='01', stock=True).pk, self.user)
        self.sale.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.sale.balance, 0)
        self.assertEqual(self.product.stock, 10)

    def test_credit_after_full_payment_and_refund(self):
        self.pay('236')
        register_note(self.note().pk, self.user)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.available_credit, 118)
        data = {'amount': Decimal('50'), 'date': timezone.localdate(), 'method': 'EFECTIVO', 'reference': 'Devolución al cliente', 'request_key': uuid.uuid4()}
        register_refund(self.sale.pk, data, self.user)
        register_refund(self.sale.pk, data, self.user)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.available_credit, 68)
        self.assertEqual(Refund.objects.count(), 1)
        with self.assertRaises(ValidationError): register_refund(self.sale.pk, {**data, 'amount': Decimal('69'), 'request_key': uuid.uuid4()}, self.user)

    def test_debit_increases_balance_without_stock_changes(self):
        register_note(self.note(amount='10', kind='DEBITO', code='02').pk, self.user)
        self.sale.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.sale.balance, 246)
        self.assertEqual(self.product.stock, 8)
        self.pay('246')
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.balance, 0)

    def test_note_retains_original_tax_and_description_after_edit(self):
        edit_product(self.product.pk, self.product_data(name='Otro nombre', tax_rate=Decimal('0'), tax_category='20'), 1, self.user)
        note = self.note()
        line = note.lines.get()
        self.assertEqual(line.tax_rate, 18)
        self.assertEqual(line.description, 'Nombre original')
        self.assertEqual(line.tax, 18)

    def test_cancel_only_drafts(self):
        note = self.note()
        cancel_draft(note.pk, self.user)
        with self.assertRaises(ValidationError): register_note(note.pk, self.user)
        with self.assertRaises(ValidationError): cancel_draft(self.sale.pk, self.user)

    def test_print_company_and_administrator_pages(self):
        for url in [f'/comprobantes/{self.sale.pk}/imprimir/', '/configuracion/empresa/',
                    '/configuracion/administradores/', '/configuracion/administradores/nuevo/', '/configuracion/']:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code, 200)

    def test_cannot_disable_self(self):
        self.client.post(f'/configuracion/administradores/{self.user.pk}/acceso/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_login_throttle(self):
        self.client.logout()
        for _ in range(8): self.client.post('/ingresar/', {'username': 'operador', 'password': 'incorrecta'})
        self.assertEqual(self.client.post('/ingresar/', {'username': 'operador', 'password': 'incorrecta'}).status_code, 429)
