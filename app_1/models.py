from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from django.apps import apps

# Model Master (Dikelola Admin/Staff)
class Item(models.Model):
    title = models.CharField(max_length=200)
    chapters = models.IntegerField(default=0)
    season = models.CharField(max_length=10, default='-', blank=True, null=True)
    
    # Gunakan tanda kutip agar Python tidak error saat membaca class yang belum didefinisikan
    status = models.ForeignKey('Status', on_delete=models.SET_DEFAULT, default=1)
    Type = models.ForeignKey('Type', on_delete=models.SET_DEFAULT, default=1)
    tags = models.ManyToManyField('Tag', blank=True)
    
    synopsis = models.TextField(default='-', blank=True, null=True)
    image = models.ImageField(upload_to='item_covers/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


# 1. MODEL Type
class Type(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Type"
        ordering = ['name']

    def __str__(self):
        return self.name

# 2. MODEL STATUS
class Status(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name_plural = "Statuses"
        ordering = ['id']

    def __str__(self):
        return self.name

# 3. MODEL IMPORT HISTORY
class ImportHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_index=True)
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='import_backups/', null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    total_items = models.IntegerField()
    status = models.CharField(max_length=50, default="Success")

    def __str__(self):
        return f"{self.filename} - {self.imported_at.strftime('%Y-%m-%d %H:%M')}"
    
# 4. MODEL TAG
class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name_plural = "Tags"
        ordering = ['name']

    def __str__(self):
        return self.name
    
# 5. MODEL READINGITEM
class ReadingItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reading_items', db_index=True)
    
    title = models.CharField(max_length=200)
    favorit = models.BooleanField(default=False)
    chapters = models.IntegerField(default=0)
    season = models.CharField(max_length=10, default='-', blank=True, null=True)
    
    status = models.ForeignKey(Status, on_delete=models.SET_DEFAULT, default=1, related_name='items')
    rating = models.CharField(max_length=10, default='-')
    
    Type = models.ForeignKey(Type, on_delete=models.SET_DEFAULT, default=1, related_name='items')
    tags = models.ManyToManyField(Tag, related_name='items', blank=True)
    
    synopsis = models.TextField(default='-', blank=True, null=True)
    notes = models.CharField(max_length=255, default='-', blank=True, null=True)
    
    image = models.ImageField(upload_to='reading_covers/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_edited_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

# 6. MODEL PROFILE
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    cover = models.ImageField(upload_to='covers/', blank=True, null=True) # Field baru
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=100, blank=True, null=True) # Field baru
    website = models.URLField(blank=True, null=True)
    social = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

# --- SIGNAL UNTUK DATA OTOMATIS ---

@receiver(post_migrate)
def create_initial_data(sender, **kwargs):
    # Menggunakan nama aplikasi 'app_1'
    if sender.name == 'app_1':
        Type = apps.get_model('app_1', 'Type')
        Status = apps.get_model('app_1', 'Status')
        Tag = apps.get_model('app_1', 'Tag')
        Item = apps.get_model('app_1', 'Item')
        
        Type.objects.update_or_create(id=1, defaults={'name': 'No Type'})
        Status.objects.update_or_create(id=1, defaults={'name': 'No Status'})
        Tag.objects.update_or_create(id=1, defaults={'name': 'No Tag'})
        
        # Tambahkan logika untuk memastikan semua item yang tidak punya tag 
        # diberikan Tag ID 1 agar sinkron dengan sistem baru
        for item in Item.objects.filter(tags__isnull=True):
            item.tags.add(1)

from django.db.models.signals import m2m_changed

@receiver(m2m_changed, sender=Item.tags.through)
def manage_tags(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        # Jika user menambah tag lain selain ID 1, hapus ID 1
        if instance.tags.count() > 1 and 1 in [pk for pk in pk_set]:
            instance.tags.remove(1)

# --- SIGNAL UNTUK PROFILE ---

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()