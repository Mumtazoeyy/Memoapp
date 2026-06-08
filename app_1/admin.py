from django.contrib import admin
from .models import Category, Status, ReadingItem, ImportHistory

# (Fungsi get_app_list tetap sama...)
def get_app_list(self, request, app_label=None):
    app_dict = self._build_app_dict(request, app_label)
    ordering = {'ReadingItem': 1, 'Category': 2, 'Status': 3, 'ImportHistory': 4}
    for app in app_dict.values():
        app['models'] = [m for m in app['models'] if m['object_name'] != 'Memo']
        app['models'].sort(key=lambda x: ordering.get(x['object_name'], 99))
    return list(app_dict.values())

admin.AdminSite.get_app_list = get_app_list

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)

@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)

@admin.register(ReadingItem)
class ReadingItemAdmin(admin.ModelAdmin):
    # 1. Menambahkan 'user' ke list_display agar admin tahu siapa pemilik datanya
    list_display = ('id', 'title', 'user', 'category', 'status', 'chapters', 'rating', 'created_at')
    list_display_links = ('id', 'title')
    list_editable = ('status', 'category', 'rating')
    list_filter = ('user', 'status', 'category', 'created_at') # 2. Filter berdasarkan user
    search_fields = ('id', 'title', 'notes', 'user__username')
    list_per_page = 50
    autocomplete_fields = ['category', 'status'] 
    
    fieldsets = (
        ('Informasi Utama', {
            'fields': ('user', 'title', 'image', 'category', 'chapters', 'season', 'rating'), # 3. Tambahkan user di fieldsets
            'description': "Data dasar untuk item bacaan."
        }),
        ('Status & Catatan', {
            'fields': ('status', 'notes', 'synopsis'),
        }),
        ('Waktu', {
            'fields': ('created_at', 'last_edited_at'),
            'classes': ('collapse',)
        }),
    )
    
    # 4. Fungsi agar admin hanya melihat data miliknya sendiri (opsional: matikan jika superuser ingin melihat semuanya)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

    readonly_fields = ('created_at', 'last_edited_at')
    ordering = ('-created_at',)

@admin.register(ImportHistory)
class ImportHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'filename', 'imported_at', 'total_items', 'status')
    list_filter = ('user', 'imported_at')
    readonly_fields = ('imported_at',)
    ordering = ('-imported_at',)