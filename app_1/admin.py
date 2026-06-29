from django.contrib import admin
from django.utils.html import format_html
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from .models import Category, Status, ReadingItem, ImportHistory
from django.contrib.auth.models import User, Group

# Paksa label model bawaan menjadi Inggris
User._meta.verbose_name = 'User'
User._meta.verbose_name_plural = 'Users'
Group._meta.verbose_name = 'Group'
Group._meta.verbose_name_plural = 'Groups'

# 1. Restore get_app_list function without hiding any models
def get_app_list(self, request, app_label=None):
    app_dict = self._build_app_dict(request, app_label)
    # Sidebar display order
    ordering = {'User': 1, 'ReadingItem': 2, 'Category': 3, 'Status': 4, 'ImportHistory': 5}
    for app in app_dict.values():
        app['models'] = [m for m in app['models'] if m['object_name'] != 'Memo']
        app['models'].sort(key=lambda x: ordering.get(x['object_name'], 99))
    return list(app_dict.values())

admin.AdminSite.get_app_list = get_app_list

# 2. Inline: Book data and history appear under the User profile
class ReadingItemInline(admin.TabularInline):
    model = ReadingItem
    extra = 0
    fields = ('title', 'category', 'status', 'chapters', 'rating')
    show_change_link = True # Click to go to item details

class ImportHistoryInline(admin.TabularInline):
    model = ImportHistory
    extra = 0
    fields = ('filename', 'imported_at', 'total_items', 'status')
    readonly_fields = ('imported_at',)
    show_change_link = True

# 3. User Registration
admin.site.unregister(User)
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = [ReadingItemInline, ImportHistoryInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')

# 4. Other Admin Models (Returned to sidebar)

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
    # 'user_username_link' in the leftmost position, followed by other information
    list_display = ('user_username_link', 'title', 'category', 'status', 'chapters', 'rating', 'created_at', 'id')
    
    # Only the title is clickable to enter the edit page
    list_display_links = ('title',) 
    
    # Direct edit feature in the table (list_editable) has been removed
    list_filter = ('user', 'status', 'category', 'created_at')
    search_fields = ('user__username', 'title', 'notes')
    list_per_page = 50
    autocomplete_fields = ['category', 'status'] 
    
    fieldsets = (
        ('Main Information', {'fields': ('user', 'title', 'image', 'category', 'chapters', 'season', 'rating')}),
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