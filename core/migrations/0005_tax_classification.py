from django.db import migrations

def classify_existing(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    Line = apps.get_model('core', 'DocumentLine')
    Document = apps.get_model('core', 'Document')
    Product.objects.filter(tax_rate=0).update(tax_category='PENDIENTE')
    Line.objects.filter(tax_rate=18).update(tax_category='10')
    # El uso de bolsas antiguas no se presume: permanece pendiente.
    # No inventar una dirección histórica con la dirección actual del cliente.
    for document in Document.objects.select_related('customer').iterator():
        if document.customer_document == document.customer.document:
            document.customer_document_type = document.customer.document_type
            document.save(update_fields=['customer_document_type'])

class Migration(migrations.Migration):
    dependencies = [('core', '0004_document_customer_address_and_more')]
    operations = [migrations.RunPython(classify_existing, migrations.RunPython.noop)]
