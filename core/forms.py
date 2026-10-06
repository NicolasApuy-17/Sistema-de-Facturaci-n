import uuid
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from .models import Company, Customer, Document, DocumentLine, Guide, Payment, Product, Refund

class StyledForm:
    def style(self):
        for field in self.fields.values():
            if isinstance(field.widget, forms.DateInput): field.widget.attrs['type'] = 'date'

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'document_type', 'document', 'address', 'phone', 'email']
    def clean(self):
        data = super().clean()
        number = data.get('document', '')
        kind = data.get('document_type')
        if kind in ('RUC', 'DNI') and (not number.isdigit() or len(number) != (11 if kind == 'RUC' else 8)):
            self.add_error('document', 'El RUC debe tener 11 dígitos y el DNI 8 dígitos.')
        return data

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'unit', 'price', 'tax_category', 'package_use', 'minimum', 'active']

    def clean(self):
        data = super().clean()
        category = data.get('tax_category')
        if category in ('10', '20', '30'):
            self.instance.tax_rate = 18 if category == '10' else 0
        # Conservar el porcentaje anterior si aún no se clasificó la operación.
        if category == 'PENDIENTE' and self.instance.pk:
            self.instance.tax_rate = Product.objects.get(pk=self.instance.pk).tax_rate
        data['tax_rate'] = self.instance.tax_rate
        return data

class ProductEditForm(ProductForm):
    expected_version = forms.IntegerField(widget=forms.HiddenInput)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['expected_version'].initial = self.instance.version

class StockForm(forms.Form):
    product = forms.ModelChoiceField(label='Producto', queryset=Product.objects.all())
    direction = forms.ChoiceField(label='Movimiento', choices=[('ENTRADA', 'Entrada'), ('SALIDA', 'Salida')])
    quantity = forms.DecimalField(label='Cantidad', min_value=0.001, max_digits=14, decimal_places=3)
    reason = forms.CharField(label='Motivo / documento de referencia', max_length=250)
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['kind', 'customer', 'reference', 'date', 'due_date', 'note_code', 'return_stock', 'notes']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}), 'due_date': forms.DateInput(attrs={'type': 'date'}), 'notes': forms.Textarea(attrs={'rows': 3})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate
        self.fields['reference'].queryset = Document.objects.filter(kind__in=['FACTURA', 'BOLETA'], status='REGISTRADO')
    def clean(self):
        data = super().clean()
        kind, customer, reference = data.get('kind'), data.get('customer'), data.get('reference')
        if kind == 'FACTURA' and customer and customer.document_type != 'RUC':
            self.add_error('customer', 'Para una factura selecciona un cliente con RUC.')
        if kind in ('CREDITO', 'DEBITO'):
            if not reference: self.add_error('reference', 'Selecciona la venta relacionada.')
            elif customer and reference.customer_id != customer.pk: self.add_error('reference', 'La venta corresponde a otro cliente.')
            if not data.get('notes'): self.add_error('notes', 'Indica el motivo de la nota.')
            allowed = ('01', '05', '07') if kind == 'CREDITO' else ('01', '02')
            if data.get('note_code') not in allowed: self.add_error('note_code', 'Selecciona un motivo compatible con el tipo de nota.')
            if data.get('return_stock') and (kind != 'CREDITO' or data.get('note_code') not in ('01', '07')):
                self.add_error('return_stock', 'Solo la anulación o devolución por ítem puede retornar mercadería.')
        elif reference:
            self.add_error('reference', 'La referencia solo corresponde a notas de crédito o débito.')
        if kind in ('FACTURA', 'BOLETA') and (data.get('note_code') or data.get('return_stock')):
            self.add_error('note_code', 'Una venta nueva no utiliza un motivo de nota ni devolución de mercadería.')
        if data.get('due_date') and data.get('date') and data['due_date'] < data['date']:
            self.add_error('due_date', 'El vencimiento no puede ser anterior a la fecha de venta.')
        return data

class LineForm(forms.Form):
    product = forms.ModelChoiceField(label='Producto', queryset=Product.objects.all())
    quantity = forms.DecimalField(label='Cantidad', min_value=0.001, max_digits=14, decimal_places=3, initial=1)
    price = forms.DecimalField(label='Precio unitario con IGV (S/)', min_value=0, max_digits=14, decimal_places=2)
    source_line = forms.ModelChoiceField(label='Solo notas: línea de venta original', queryset=DocumentLine.objects.filter(document__kind__in=['FACTURA', 'BOLETA'], document__status='REGISTRADO').select_related('document'), required=False)

LineFormSet = forms.formset_factory(LineForm, extra=1, min_num=1, validate_min=True, max_num=100, validate_max=True, can_delete=True)

class PaymentForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    class Meta:
        model = Payment
        fields = ['amount', 'date', 'method', 'reference', 'request_key']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate

class GuideForm(forms.ModelForm):
    class Meta:
        model = Guide
        exclude = ['created_by', 'created_at', 'status', 'goods']
        widgets = {'transfer_date': forms.DateInput(attrs={'type': 'date'}), 'goods': forms.Textarea(attrs={'rows': 4})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['transfer_date'].initial = timezone.localdate
        self.fields['sale'].queryset = Document.objects.filter(kind__in=['FACTURA', 'BOLETA'], status='REGISTRADO')
    def clean(self):
        data = super().clean()
        if data.get('sale') and data.get('customer') and data['sale'].customer_id != data['customer'].pk:
            self.add_error('sale', 'La venta corresponde a otro destinatario.')
        if data.get('transport_mode') == 'PUBLICO' or data.get('kind') == 'TRANSPORTISTA':
            if not (data.get('carrier_ruc', '').isdigit() and len(data.get('carrier_ruc', '')) == 11):
                self.add_error('carrier_ruc', 'Ingresa el RUC de 11 dígitos del transportista.')
            if not data.get('carrier_name'): self.add_error('carrier_name', 'Ingresa la razón social del transportista.')
        if data.get('transport_mode') == 'PRIVADO' or data.get('kind') == 'TRANSPORTISTA':
            for name in ['plate', 'driver_document', 'driver_license']:
                if not data.get(name): self.add_error(name, 'Completa este dato del transporte.')
        if data.get('kind') == 'TRANSPORTISTA' and not data.get('related_gre'):
            self.add_error('related_gre', 'Indica la GRE remitente relacionada. Los supuestos de excepción se implementarán posteriormente.')
        return data

class GuideLineForm(forms.Form):
    product = forms.ModelChoiceField(label='Producto', queryset=Product.objects.all())
    quantity = forms.DecimalField(label='Cantidad a trasladar', min_value=0.001, max_digits=14, decimal_places=3)

GuideLineFormSet = forms.formset_factory(GuideLineForm, extra=0, min_num=1, validate_min=True, max_num=100, validate_max=True, can_delete=True)

class RefundForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    class Meta:
        model = Refund
        fields = ['amount', 'date', 'method', 'reference', 'request_key']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = timezone.localdate

class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'ruc', 'address', 'ubigeo', 'regime', 'ose_required']
    def clean(self):
        data = super().clean()
        if data.get('ruc') and (not data['ruc'].isdigit() or len(data['ruc']) != 11): self.add_error('ruc', 'Ingresa un RUC de 11 dígitos.')
        if data.get('ubigeo') and (not data['ubigeo'].isdigit() or len(data['ubigeo']) != 6): self.add_error('ubigeo', 'Ingresa un ubigeo de 6 dígitos.')
        return data

class AdministratorForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name']
