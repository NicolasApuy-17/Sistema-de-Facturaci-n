from django.db import migrations

def preserve_history(apps, schema_editor):
    alias = schema_editor.connection.alias
    Movement = apps.get_model('core', 'StockMovement')
    Line = apps.get_model('core', 'DocumentLine')
    for row in Movement.objects.using(alias).select_related('product').iterator():
        row.product_name = row.product.name
        row.product_sku = row.product.sku
        row.product_unit = row.product.unit
        row.save(using=alias, update_fields=['product_name', 'product_sku', 'product_unit'])
    for row in Line.objects.using(alias).select_related('product').iterator():
        row.sku = row.product.sku
        row.save(using=alias, update_fields=['sku'])

class Migration(migrations.Migration):
    dependencies = [('core', '0002_operations')]
    operations = [migrations.RunPython(preserve_history, migrations.RunPython.noop)]
