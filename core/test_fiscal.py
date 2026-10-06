from datetime import timedelta
from decimal import Decimal
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from lxml import etree
from .fiscal.ubl import build_preview, NS
from .forms import ProductForm
from .models import Company, Customer, Product, StockMovement
from .services import create_document, edit_product, move_stock, register_sale

class FiscalPreviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('admin_xml', is_staff=True)
        self.client.force_login(self.user)
        self.company = Company.objects.create(name='Empresa & Envases', ruc='20123456789', address='Av. Prueba 123', ubigeo='150101', regime='GENERAL')
        self.customer = Customer.objects.create(name='Cliente <prueba>', document='20987654321', document_type='RUC', address='Dirección original')
        self.product = Product.objects.create(sku='ENV-01', name='Bolsa alimenticia & arroz', price=Decimal('1.18'), package_use='ALIMENTO')

    def draft(self, kind='FACTURA', product=None, **extra):
        return create_document({'kind': kind, 'customer': self.customer, 'date': timezone.localdate(), **extra},
            [{'product': product or self.product, 'quantity': Decimal('100'), 'price': (product or self.product).price}], self.user)

    def xml(self, doc): return etree.fromstring(build_preview(doc, self.company))

    def test_food_packaging_keeps_igv_and_has_no_icbper(self):
        doc = self.draft()
        root = self.xml(doc)
        self.assertEqual(doc.tax, Decimal('18'))
        self.assertEqual(root.xpath('string(cac:TaxTotal/cbc:TaxAmount)', namespaces=NS), '18.00')
        self.assertEqual(root.xpath('string(cac:InvoiceLine/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReasonCode)', namespaces=NS), '10')
        self.assertNotIn('7152', etree.tostring(root).decode())
        self.assertIn('PRUEBA SIN FIRMA', etree.tostring(root).decode())
        self.assertEqual(root.xpath('string(cac:InvoiceLine/cac:Item/cbc:Description)', namespaces=NS), self.product.name)

    def test_boleta_and_notes_pass_xsd(self):
        sale = self.draft(kind='BOLETA')
        self.xml(sale)
        move_stock(self.product.pk, Decimal('100'), 'Entrada', self.user, uuid.uuid4())
        register_sale(sale.pk, self.user)
        for kind, code in [('CREDITO', '07'), ('DEBITO', '02')]:
            note = create_document({'kind': kind, 'customer': self.customer, 'date': timezone.localdate(), 'reference': sale,
                'note_code': code, 'notes': 'Corrección de prueba'}, [{'product': self.product, 'quantity': Decimal('1'),
                'price': Decimal('1.18'), 'source_line': sale.lines.get()}], self.user)
            root = self.xml(note)
            self.assertEqual(root.xpath('string(cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID)', namespaces=NS), f'BPRV-{sale.pk}')

    def test_exonerated_and_unaffected_have_distinct_tax_codes(self):
        for category, tax_id in [('20', '9997'), ('30', '9998')]:
            product = Product.objects.create(sku=category, name='Clasificado', price=10, tax_rate=0, tax_category=category, package_use='NO_APLICA')
            root = self.xml(self.draft(product=product))
            self.assertEqual(root.xpath('string(cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cac:TaxScheme/cbc:ID)', namespaces=NS), tax_id)

    def test_mixed_tax_groups_and_fractional_quantity_pass_xsd(self):
        exempt = Product.objects.create(sku='EXO', name='Exonerado', price=10, tax_rate=0, tax_category='20', package_use='NO_APLICA')
        doc = create_document({'kind': 'FACTURA', 'customer': self.customer, 'date': timezone.localdate()},
            [{'product': self.product, 'quantity': Decimal('2.345'), 'price': Decimal('1.18')},
             {'product': exempt, 'quantity': Decimal('3'), 'price': Decimal('10')}], self.user)
        root = self.xml(doc)
        self.assertEqual(len(root.xpath('cac:TaxTotal/cac:TaxSubtotal', namespaces=NS)), 2)
        self.assertEqual(root.xpath('string(cac:LegalMonetaryTotal/cbc:PayableAmount)', namespaces=NS), str(doc.total))

    def test_historical_customer_and_tax_are_not_replaced_by_current_values(self):
        doc = self.draft()
        self.customer.name = 'Nombre nuevo'; self.customer.address = 'Dirección nueva'; self.customer.save()
        self.product.package_use = 'TRANSPORTE'; self.product.tax_rate = 0; self.product.tax_category = '20'; self.product.save()
        root = self.xml(doc)
        self.assertEqual(root.xpath('string(cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName)', namespaces=NS), 'Cliente <prueba>')
        self.assertIn('Dirección original', etree.tostring(root, encoding='unicode'))
        self.assertEqual(doc.lines.get().tax_category, '10')

    def test_unclassified_and_transport_bags_cannot_generate_misleading_xml(self):
        for use in ['PENDIENTE', 'TRANSPORTE']:
            self.product.package_use = use; self.product.save()
            with self.assertRaises(ValidationError): self.xml(self.draft())

    def test_credit_sale_not_silently_exported_as_cash(self):
        with self.assertRaises(ValidationError): self.xml(self.draft(due_date=timezone.localdate() + timedelta(days=30)))

    def test_missing_company_or_inconsistent_tax_block_preview(self):
        doc = self.draft()
        with self.assertRaises(ValidationError): build_preview(doc, None)
        doc.lines.update(tax_category='20')
        with self.assertRaises(ValidationError): self.xml(doc)

    def test_download_is_admin_only_and_does_not_register_sale_or_send(self):
        doc = self.draft()
        response = self.client.get(f'/comprobantes/{doc.pk}/xml-prueba/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('PRUEBA-', response['Content-Disposition'])
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'BORRADOR')
        self.assertEqual(doc.sunat_status, 'NO_ENVIADO')
        self.assertEqual(StockMovement.objects.count(), 0)
        self.user.is_staff = False; self.user.save()
        self.assertEqual(self.client.get(f'/comprobantes/{doc.pk}/xml-prueba/').status_code, 403)

    def test_product_form_derives_rate_independently_of_food_use(self):
        for category, rate in [('10', Decimal('18')), ('20', Decimal('0')), ('30', Decimal('0'))]:
            form = ProductForm({'sku': 'FORM-' + category, 'name': 'Bolsa para alimentos', 'unit': 'NIU', 'price': '1.18',
                'tax_category': category, 'package_use': 'ALIMENTO', 'minimum': '0', 'active': True})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.save().tax_rate, rate)

    def test_pending_classification_does_not_invent_zero_igv(self):
        form = ProductForm({'sku': 'SIN-CLASIFICAR', 'name': 'Nuevo', 'unit': 'NIU', 'price': '1.18',
            'tax_category': 'PENDIENTE', 'package_use': 'PENDIENTE', 'minimum': '0', 'active': True})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().tax_rate, Decimal('18'))

    def test_inconsistent_classification_cannot_be_saved_by_edit_service(self):
        data = {name: getattr(self.product, name) for name in ['sku', 'name', 'unit', 'price', 'tax_rate', 'tax_category', 'package_use', 'minimum', 'active']}
        with self.assertRaises(ValidationError): edit_product(self.product.pk, {**data, 'tax_category': '20'}, 1, self.user)
