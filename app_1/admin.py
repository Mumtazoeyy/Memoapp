from django.contrib import admin
from .models import Memo, Category, Status, ReadingItem

@admin.register(Memo)
class MemoAdmin(admin.ModelAdmin):
    list_display = ('id', 'judul', 'tanggal_dibuat')
    list_display_links = ('id', 'judul') # Klik ID atau Judul untuk buka item
    search_fields = ('judul',)
    list_filter = ('tanggal_dibuat',)
    list_per_page = 20

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    list_display_links = ('id', 'name')
    search_fields = ('name',)

@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    list_display_links = ('id', 'name')
    search_fields = ('name',)

@admin.register(ReadingItem)
class ReadingItemAdmin(admin.ModelAdmin):
    # Mengelompokkan list_display agar lebih mudah dibaca
    list_display = ('id', 'title', 'category', 'status', 'chapters', 'rating', 'created_at')
    list_display_links = ('id', 'title') # Klik link hanya di ID atau Title
    
    # Mempermudah edit cepat di halaman daftar
    list_editable = ('status', 'category', 'rating')
    
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('id', 'title', 'notes')
    
    # Menjaga performa tetap ringan
    list_per_page = 50
    autocomplete_fields = ['category', 'status'] 
    
    fieldsets = (
        ('Informasi Utama', {
            'fields': ('title', 'image', 'category', 'chapters', 'season', 'rating'),
            'description': "Data dasar untuk item bacaan."
        }),
        ('Status & Catatan', {
            'fields': ('status', 'notes', 'synopsis'),
        }),
        ('Waktu', {
            'fields': ('created_at', 'last_edited_at'),
            'classes': ('collapse',) # Sembunyikan agar form utama tidak terlalu panjang
        }),
    )
    
    readonly_fields = ('created_at', 'last_edited_at')
    ordering = ('-created_at',)