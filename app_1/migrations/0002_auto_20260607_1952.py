from django.db import migrations

def create_initial_data(apps, schema_editor):
    Category = apps.get_model('app_1', 'Category')
    Status = apps.get_model('app_1', 'Status')
    
    # Menjamin ID 1 tetap konsisten di semua tempat (lokal & hosting)
    Category.objects.get_or_create(id=1, defaults={'name': 'No Category'})
    for cat in ["Manga", "Manhua", "Manhwa"]:
        Category.objects.get_or_create(name=cat)
    
    Status.objects.get_or_create(id=1, defaults={'name': 'No Status'})
    for stat in ["On Going", "Completed"]:
        Status.objects.get_or_create(name=stat)

class Migration(migrations.Migration):
    dependencies = [
        ('app_1', '0001_initial'), # Pastikan ini nama file migrasi sebelumnya
    ]

    operations = [
        migrations.RunPython(create_initial_data),
    ]