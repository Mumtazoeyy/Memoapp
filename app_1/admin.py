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
from django.db import transaction
from django import forms
from django.core.exceptions import ValidationError

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
# ==========================================================
# TAG ADMIN - SINGLE & BULK IMPORT
# ==========================================================

class TagAdminForm(forms.ModelForm):
    IMPORT_CHOICES = [
        ('single', 'Single Tag'),
        ('bulk', 'Bulk Import'),
    ]

    name = forms.CharField(
        required=False,
        max_length=50,
        label='Name',
    )

    import_mode = forms.ChoiceField(
        choices=IMPORT_CHOICES,
        initial='single',
        required=True,
        label='Import Mode',
    )

    bulk_tags = forms.CharField(
        required=False,
        label='Tags (One per line)',
        widget=forms.Textarea(attrs={
            'rows': 12,
            'placeholder': 'System\nStatus\nCrime\nMafia\nGangs',
            'style': 'width: 100%; max-width: 600px;',
        })
    )

    class Meta:
        model = Tag
        fields = ('name',)

    def _get_validation_exclusions(self):
        exclude = super()._get_validation_exclusions()

        if self.data.get('import_mode') == 'bulk':
            exclude.add('name')

        return exclude

    def clean(self):
        cleaned_data = super().clean()

        mode = cleaned_data.get('import_mode')

        if mode == 'single':
            name = (cleaned_data.get('name') or '').strip()

            if not name:
                self.add_error('name', 'Nama Tag wajib diisi.')
            else:
                cleaned_data['name'] = name

        elif mode == 'bulk':
            bulk_tags = cleaned_data.get('bulk_tags') or ''

            names = [
                line.strip()
                for line in bulk_tags.splitlines()
                if line.strip()
            ]

            if not names:
                self.add_error(
                    'bulk_tags',
                    'Masukkan minimal satu nama Tag.'
                )

            too_long = [
                name for name in names
                if len(name) > 50
            ]

            if too_long:
                self.add_error(
                    'bulk_tags',
                    f'{len(too_long)} Tag melebihi batas 50 karakter.'
                )

        return cleaned_data


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    form = TagAdminForm

    list_display = ('id', 'name')
    search_fields = ('name',)
    ordering = ('id',)

    class Media:
        js = ('admin/js/tag_bulk_import.js',)

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get('import_mode') == 'single':
            super().save_model(request, obj, form, change)

    def add_view(self, request, form_url='', extra_context=None):
        if request.method == 'POST':
            form = self.get_form(request)(
                request.POST,
                request.FILES
            )

            if form.is_valid():
                if form.cleaned_data.get('import_mode') == 'bulk':
                    names = [
                        line.strip()
                        for line in form.cleaned_data['bulk_tags'].splitlines()
                        if line.strip()
                    ]

                    created_count = 0
                    existing_count = 0

                    try:
                        with transaction.atomic():
                            for name in names:
                                _, created = Tag.objects.get_or_create(
                                    name=name
                                )

                                if created:
                                    created_count += 1
                                else:
                                    existing_count += 1

                        messages.success(
                            request,
                            f'{created_count} Tag baru berhasil ditambahkan.'
                        )

                        if existing_count:
                            messages.warning(
                                request,
                                f'{existing_count} Tag sudah tersedia dan dilewati.'
                            )

                        return redirect('admin:app_1_tag_changelist')

                    except Exception as e:
                        messages.error(request, f'Import gagal: {e}')

        return super().add_view(
            request,
            form_url,
            extra_context
        )

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