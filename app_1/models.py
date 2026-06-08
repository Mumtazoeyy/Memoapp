from django.db import models
from django.contrib.auth.models import User 

# 1. MODEL CATEGORY
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Categories"
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
    # Menambahkan db_index=True agar query histori per user lebih cepat
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_index=True)
    filename = models.CharField(max_length=255)
    imported_at = models.DateTimeField(auto_now_add=True)
    total_items = models.IntegerField()
    status = models.CharField(max_length=50, default="Success")

    def __str__(self):
        return f"{self.filename} - {self.imported_at.strftime('%Y-%m-%d %H:%M')}"
    
# 4. MODEL READINGITEM
class ReadingItem(models.Model):
    # Menambahkan db_index=True pada user agar query list per user sangat cepat
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reading_items', db_index=True)
    
    title = models.CharField(max_length=200)
    favorit = models.BooleanField(default=False)
    chapters = models.IntegerField(default=0)
    season = models.CharField(max_length=10, default='-', blank=True, null=True)
    
    status = models.ForeignKey(Status, on_delete=models.SET_DEFAULT, default=1, related_name='items')
    rating = models.CharField(max_length=10, default='-')
    
    category = models.ForeignKey(Category, on_delete=models.SET_DEFAULT, default=1, related_name='items')
    
    synopsis = models.TextField(default='-', blank=True, null=True)
    notes = models.CharField(max_length=255, default='-', blank=True, null=True)
    
    image = models.ImageField(upload_to='reading_covers/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_edited_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title