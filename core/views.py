from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from .forms import AdministratorForm, CompanyForm, CustomerForm, DocumentForm, GuideForm, GuideLineFormSet, LineFormSet, PaymentForm, ProductEditForm, ProductForm, RefundForm, StockForm
from .models import AuditEvent, Company, Customer, Document, DocumentLine, Guide, Payment, Product, Refund, StockMovement
from .services import audit, cancel_draft, create_document, create_guide, edit_product, move_stock, register_note, register_payment, register_refund, register_sale

def balance_expression(): return F('total') + F('debited') - F('credited') - F('paid') + F('refunded')

def administrator(view):
    @login_required
    @wraps(view)
    def secured(request, *args, **kwargs):
        if not request.user.is_staff: raise PermissionDenied
        return view(request, *args, **kwargs)
    return secured

@administrator
def dashboard(request):
    sales = Document.objects.filter(status='REGISTRADO', kind__in=['FACTURA', 'BOLETA'])
    return render(request, 'dashboard.html', {
        'sales_total': sales.aggregate(n=Sum('total'))['n'] or 0,
        'balance_total': sales.aggregate(n=Sum(balance_expression()))['n'] or 0,
        'customer_count': Customer.objects.count(), 'product_count': Product.objects.count(),
        'low_stock': Product.objects.filter(stock__lte=F('minimum'))[:8], 'recent': Document.objects.select_related('customer')[:6]})

@administrator
def customers(request):
    query = request.GET.get('q', '').strip()
    rows = Customer.objects.filter(Q(name__icontains=query) | Q(document__icontains=query))[:200]
    return render(request, 'customers.html', {'rows': rows, 'q': query})

@administrator
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            customer = form.save()
            audit(request.user, 'Crear cliente', customer)
        messages.success(request, 'Cliente registrado.')
        return redirect('customers')
    return render(request, 'form.html', {'form': form, 'title': 'Nuevo cliente', 'back': '/clientes/'})

@administrator
def account(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sales = Document.objects.filter(customer=customer, status='REGISTRADO', kind__in=['FACTURA', 'BOLETA'])
    return render(request, 'account.html', {'customer': customer, 'sales': sales,
        'balance': sales.aggregate(n=Sum(balance_expression()))['n'] or 0,
        'payments': Payment.objects.filter(document__customer=customer).select_related('document')[:100],
        'adjustments': Document.objects.filter(customer=customer, status='REGISTRADO', kind__in=['CREDITO', 'DEBITO']).select_related('reference'),
        'refunds': Refund.objects.filter(document__customer=customer).select_related('document')})

@administrator
def products(request):
    query = request.GET.get('q', '').strip()
    rows = Product.objects.filter(Q(name__icontains=query) | Q(sku__icontains=query))[:200]
    return render(request, 'products.html', {'rows': rows, 'q': query, 'movements': StockMovement.objects.select_related('product', 'created_by')[:30]})

@administrator
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = form.save()
            audit(request.user, 'Crear producto', product)
        messages.success(request, 'Producto registrado. Ingresa existencias desde Nuevo movimiento.')
        return redirect('products')
    return render(request, 'form.html', {'form': form, 'title': 'Nuevo producto', 'back': '/inventario/'})

@administrator
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductEditForm(request.POST or None, instance=product)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data.copy()
        expected = data.pop('expected_version')
        try: edit_product(pk, data, expected, request.user)
        except ValidationError as exc: form.add_error(None, exc)
        else:
            messages.success(request, 'Producto actualizado. El historial y las existencias se conservaron.')
            return redirect('products')
    return render(request, 'form.html', {'form': form, 'title': 'Editar producto', 'subtitle': 'El stock se modifica únicamente mediante movimientos. La unidad se conserva si hay historial.', 'back': '/inventario/'})

@administrator
def stock_create(request):
    form = StockForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            delta = data['quantity'] if data['direction'] == 'ENTRADA' else -data['quantity']
            move_stock(data['product'].pk, delta, data['reason'], request.user, data['request_key'])
        except ValidationError as exc: form.add_error(None, exc)
        else:
            messages.success(request, 'Movimiento de inventario registrado.')
            return redirect('products')
    return render(request, 'form.html', {'form': form, 'title': 'Movimiento de inventario', 'back': '/inventario/'})

@administrator
def documents(request):
    return render(request, 'documents.html', {'rows': Document.objects.select_related('customer')[:200]})

@administrator
def document_create(request):
    form = DocumentForm(request.POST or None)
    formset = LineFormSet(request.POST or None, prefix='lines')
    if request.method == 'POST':
        valid_form, valid_lines = form.is_valid(), formset.is_valid()
        if valid_form and valid_lines:
            try:
                doc = create_document(form.cleaned_data, [f.cleaned_data for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE')], request.user)
            except ValidationError as exc: form.add_error(None, exc)
            else: return redirect('document_detail', pk=doc.pk)
    return render(request, 'document_form.html', {'form': form, 'formset': formset, 'products': list(Product.objects.values('id', 'price')),
        'source_lines': list(DocumentLine.objects.filter(document__kind__in=['FACTURA', 'BOLETA'], document__status='REGISTRADO').values('id', 'product_id', 'price', 'quantity'))})

@administrator
def document_detail(request, pk):
    return render(request, 'document_detail.html', {'doc': get_object_or_404(Document, pk=pk)})

@administrator
def document_xml_preview(request, pk):
    from .fiscal.ubl import build_preview, KINDS, preview_id
    doc = get_object_or_404(Document.objects.select_related('reference'), pk=pk)
    try:
        content = build_preview(doc, Company.objects.first())
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
        return redirect('document_detail', pk=pk)
    filename = f'PRUEBA-{KINDS[doc.kind][1]}-{preview_id(doc)}.xml'
    response = HttpResponse(content, content_type='application/xml; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'no-store'
    return response

@require_POST
@administrator
def document_register(request, pk):
    get_object_or_404(Document, pk=pk)
    try:
        doc = Document.objects.get(pk=pk)
        if doc.kind in ('CREDITO', 'DEBITO'): register_note(pk, request.user)
        else: register_sale(pk, request.user)
    except ValidationError as exc: messages.error(request, ' '.join(exc.messages))
    else: messages.success(request, 'Operación interna registrada y cuenta actualizada. No se ha emitido ante SUNAT.')
    return redirect('document_detail', pk=pk)

@administrator
def payment_create(request, pk):
    doc = get_object_or_404(Document, pk=pk, status='REGISTRADO', kind__in=['FACTURA', 'BOLETA'])
    form = PaymentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try: register_payment(pk, form.cleaned_data, request.user)
        except ValidationError as exc: form.add_error(None, exc)
        else:
            messages.success(request, 'Pago registrado.')
            return redirect('account', pk=doc.customer_id)
    return render(request, 'form.html', {'form': form, 'title': f'Registrar pago · {doc.code}', 'subtitle': f'Saldo pendiente: S/ {doc.balance}', 'back': f'/clientes/{doc.customer_id}/cuenta/'})

@administrator
def guides(request):
    return render(request, 'guides.html', {'rows': Guide.objects.select_related('customer')[:200]})

@administrator
def guide_create(request):
    form = GuideForm(request.POST or None)
    lines = GuideLineFormSet(request.POST or None, prefix='goods')
    if request.method == 'POST':
        valid_form, valid_lines = form.is_valid(), lines.is_valid()
        if valid_form and valid_lines:
            try: guide = create_guide(form.cleaned_data, [f.cleaned_data for f in lines if f.cleaned_data and not f.cleaned_data.get('DELETE')], request.user)
            except ValidationError as exc: form.add_error(None, exc)
            else:
                messages.success(request, 'Guía guardada como borrador. No modifica stock ni está emitida ante SUNAT.')
                return redirect('guide_detail', pk=guide.pk)
    return render(request, 'guide_form.html', {'form': form, 'formset': lines})

@administrator
def guide_detail(request, pk):
    return render(request, 'guide_detail.html', {'guide': get_object_or_404(Guide, pk=pk)})

@administrator
def settings_page(request):
    from .readiness import readiness
    return render(request, 'settings.html', {'events': AuditEvent.objects.select_related('user')[:30], 'readiness': readiness()})

@administrator
def company_edit(request):
    company = Company.objects.first() or Company()
    form = CompanyForm(request.POST or None, instance=company)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            company = form.save()
            audit(request.user, 'Configurar empresa', company)
        messages.success(request, 'Datos de la empresa guardados.')
        return redirect('settings')
    return render(request, 'form.html', {'form': form, 'title': 'Datos de la empresa', 'back': '/configuracion/'})

@administrator
def refund_create(request, pk):
    doc = get_object_or_404(Document, pk=pk, status='REGISTRADO', kind__in=['FACTURA', 'BOLETA'])
    form = RefundForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try: register_refund(pk, form.cleaned_data, request.user)
        except ValidationError as exc: form.add_error(None, exc)
        else:
            messages.success(request, 'Devolución de dinero registrada.')
            return redirect('account', pk=doc.customer_id)
    return render(request, 'form.html', {'form': form, 'title': f'Devolver dinero · {doc.code}', 'subtitle': f'Saldo a favor disponible: S/ {doc.available_credit}', 'back': f'/clientes/{doc.customer_id}/cuenta/'})

@require_POST
@administrator
def document_cancel(request, pk):
    get_object_or_404(Document, pk=pk)
    try: cancel_draft(pk, request.user)
    except ValidationError as exc: messages.error(request, ' '.join(exc.messages))
    else: messages.success(request, 'Borrador cancelado sin modificar saldos ni inventario.')
    return redirect('document_detail', pk=pk)

@administrator
def document_print(request, pk):
    return render(request, 'print_document.html', {'doc': get_object_or_404(Document, pk=pk), 'company': Company.objects.first()})

@administrator
def guide_print(request, pk):
    return render(request, 'print_guide.html', {'guide': get_object_or_404(Guide, pk=pk), 'company': Company.objects.first()})

@administrator
def administrators(request):
    return render(request, 'administrators.html', {'rows': get_user_model().objects.filter(is_staff=True).order_by('username')})

@administrator
def administrator_create(request):
    form = AdministratorForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save(commit=False)
            user.is_staff = True
            user.save()
            audit(request.user, 'Crear administrador', user)
        messages.success(request, 'Administrador creado. Tiene acceso a las operaciones del sistema.')
        return redirect('administrators')
    return render(request, 'form.html', {'form': form, 'title': 'Nuevo administrador', 'back': '/configuracion/administradores/'})

@require_POST
@administrator
def administrator_toggle(request, pk):
    with transaction.atomic():
        users = list(get_user_model().objects.select_for_update().filter(is_staff=True).order_by('pk'))
        target = next((user for user in users if user.pk == pk), None)
        if not target: raise PermissionDenied
        if target.pk == request.user.pk:
            messages.error(request, 'No puedes desactivar tu propio acceso.')
        elif target.is_active and sum(user.is_active for user in users) <= 1:
            messages.error(request, 'Debe quedar al menos un administrador activo.')
        else:
            target.is_active = not target.is_active
            target.save(update_fields=['is_active'])
            audit(request.user, 'Cambiar acceso administrador', target, 'Activo' if target.is_active else 'Desactivado')
            messages.success(request, 'Acceso actualizado.')
    return redirect('administrators')
