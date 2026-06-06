from django.db import models

# 1. MODEL MEMO
class Memo(models.Model):
    judul = models.CharField(max_length=200)
    isi = models.TextField()
    tanggal_dibuat = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.judul


# 2. MODEL CATEGORY
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']  # Tambahkan ini agar list di dropdown selalu rapi (A-Z)

    def __str__(self):
        return self.name


# 3. MODEL STATUS
class Status(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name_plural = "Statuses"
        ordering = ['id']  # Status biasanya lebih enak diurutkan berdasarkan alur (ID)

    def __str__(self):
        return self.name


# 4. MODEL READINGITEM
class ReadingItem(models.Model):
    # Field Dasar
    title = models.CharField(max_length=200)
    chapters = models.IntegerField(default=0)
    season = models.CharField(max_length=10, default='-', blank=True, null=True)
    
    # Status (CharField sesuai permintaan)
    status = models.ForeignKey(Status, on_delete=models.SET_DEFAULT, default=1, related_name='items')
    # Rating (Ganti dari Hype)
    rating = models.CharField(max_length=10, default='-')
    
    # Relasi Kategori
    category = models.ForeignKey(Category, on_delete=models.SET_DEFAULT, default=1, related_name='items')
    
    # Synopsis dan Notes (Dipisah)
    synopsis = models.TextField(default='-', blank=True, null=True)
    notes = models.CharField(max_length=255, default='-', blank=True, null=True)
    
    image = models.ImageField(upload_to='reading_covers/', blank=True, null=True)

    # Waktu
    created_at = models.DateTimeField(auto_now_add=True)
    last_edited_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title