import json
from django.contrib import admin
from django.utils.html import format_html
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.contrib import messages
# 1. Tambahkan Tag ke import
from .models import Item, Profile, Type, Status, ReadingItem, ImportHistory, Tag
from django.contrib.auth.models import User, Group

# Paksa label model bawaan menjadi Inggris
User._meta.verbose_name = 'User'
User._meta.verbose_name_plural = 'Users'
Group._meta.verbose_name = 'Group'
Group._meta.verbose_name_plural = 'Groups'

# 1. Restore get_app_list function
def get_app_list(self, request, app_label=None):
    app_dict = self._build_app_dict(request, app_label)
    # 2. Tambahkan Tag ke ordering sidebar
    ordering = {'User': 1, 'Item': 2, 'ReadingItem': 3, 'Type': 4, 'Status': 5, 'Tag': 6, 'ImportHistory': 7}
    for app in app_dict.values():
        app['models'] = [m for m in app['models'] if m['object_name'] != 'Memo']
        app['models'].sort(key=lambda x: ordering.get(x['object_name'], 99))
    return list(app_dict.values())

admin.AdminSite.get_app_list = get_app_list

# ... (Inline classes tetap sama) ...
class ReadingItemInline(admin.TabularInline):
    model = ReadingItem
    extra = 0
    fields = ('title', 'Type', 'status', 'chapters', 'rating')
    show_change_link = True

class ImportHistoryInline(admin.TabularInline):
    model = ImportHistory
    extra = 0
    fields = ('filename', 'imported_at', 'total_items', 'status')
    readonly_fields = ('imported_at',)
    show_change_link = True

# 3. User Registration tetap sama
admin.site.unregister(User)
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = [ReadingItemInline, ImportHistoryInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')

# 4. Admin Models
@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    autocomplete_fields = ['Type', 'status', 'tags']

    def get_changeform_initial_data(self, request):
        return {'tags': [1]}

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.tags.exists():
            obj.tags.add(1)

@admin.register(Type)
class TypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)

@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)

# 5. TagAdmin dengan Tambahan Fitur Import JSON
@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    ordering = ('id',) # <-- Tambahkan baris ini agar otomatis urut berdasarkan ID
    
    def changelist_view(self, request, extra_context=None):
        import_url = reverse('admin:app_1_tag_import_json')
        msg = format_html(
            '<b>Fitur Cepat:</b> Ingin memasukkan banyak tag sekaligus? '
            '<a href="{}" class="button" style="background: #417690; color: white; padding: 3px 10px; border-radius: 4px; text-decoration: none; margin-left: 5px; border: 1px solid white;">Klik di sini untuk Import JSON</a>',
            import_url
        )
        if not any(m.message.startswith('<b>Fitur Cepat:</b>') for m in request._messages):
            messages.info(request, msg)
        return super().changelist_view(request, extra_context=extra_context)
    
    # Menambahkan URL kustom untuk proses import JSON di panel admin
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-json/', self.admin_site.admin_view(self.import_json_tags), name='app_1_tag_import_json'),
        ]
        return custom_urls + urls

    # View kustom untuk menangani upload file JSON
    def import_json_tags(self, request):
        if request.method == 'POST':
            json_file = request.FILES.get('json_file')
            if not json_file:
                messages.error(request, "Harap unggah file JSON terlebih dahulu!")
                return redirect('..')

            try:
                file_data = json_file.read().decode('utf-8')
                tags_data = json.loads(file_data)

                count = 0
                for item in tags_data:
                    tag, created = Tag.objects.update_or_create(
                        id=item.get('id'),
                        defaults={'name': item.get('name')}
                    )
                    if created:
                        count += 1

                messages.success(request, f"Sukses! {count} tag baru berhasil di-import ke database.")
            except Exception as e:
                messages.error(request, f"Gagal memproses file JSON: {e}")

            return redirect('..')

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Import Tags from JSON',
        }
        return render(request, 'admin/import_tags_form.html', context)

@admin.register(ReadingItem)
class ReadingItemAdmin(admin.ModelAdmin):
    list_display = ('user_username_link', 'title', 'Type', 'status', 'chapters', 'rating', 'created_at', 'id')
    list_display_links = ('title',) 
    list_filter = ('user', 'status', 'Type', 'created_at')
    search_fields = ('user__username', 'title', 'notes')
    list_per_page = 50
    autocomplete_fields = ['Type', 'status'] 
    
    fieldsets = (
        ('Main Information', {'fields': ('user', 'title', 'image', 'Type', 'chapters', 'season', 'rating', 'tags')}),
        ('Status & Notes', {'fields': ('status', 'notes', 'synopsis')}),
        ('Time', {'fields': ('created_at', 'last_edited_at'), 'classes': ('collapse',)}),
    )
    
    ordering = ('user', '-created_at')

    def user_username_link(self, obj):
        url = f"?user__id__exact={obj.user.id}"
        return format_html('<a href="{}"><b>{}</b></a>', url, obj.user.username)
    user_username_link.short_description = 'User'
    user_username_link.admin_order_field = 'user'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

    readonly_fields = ('created_at', 'last_edited_at')

@admin.register(ImportHistory)
class ImportHistoryAdmin(admin.ModelAdmin):
    list_display = ('user_username_link', 'filename', 'imported_at', 'total_items', 'status')
    list_filter = ('user', 'imported_at')
    readonly_fields = ('imported_at',)
    ordering = ('user', '-imported_at')

    def user_username_link(self, obj):
        url = f"?user__id__exact={obj.user.id}"
        return format_html('<a href="{}"><b>{}</b></a>', url, obj.user.username)
    user_username_link.short_description = 'User'
    user_username_link.admin_order_field = 'user'

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'location', 'website', 'social')