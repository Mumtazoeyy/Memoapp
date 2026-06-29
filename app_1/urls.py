from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    # Main Reading List
    path('', views.reading_list, name='reading_list'),

    # Management
    path('add/', views.reading_add, name='reading_add'),
    path('edit/<int:pk>/', views.reading_edit, name='reading_edit'),
    path('edit-bulk/', views.reading_edit_bulk, name='reading_edit_bulk'),
    path('delete/<int:pk>/', views.reading_delete, name='reading_delete'),
    path('delete-selected/', views.delete_selected, name='delete_selected'),
    path('item/<int:pk>/toggle-favorite/', views.toggle_favorite, name='toggle_favorite'),

    # Utility & Data
    path('search/', views.search_view, name='search'),
    path('import/data/', views.import_data, name='import_data'),
    path('import/full/', views.import_full, name='import_full'),
    path('export/data/', views.export_data, name='export_data'),
    path('export/full/', views.export_full, name='export_full'),
    path('about/', views.about_view, name='about'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('detail/<int:item_id>/', views.reading_item_detail, name='reading_item_detail'),
    path('history/', views.history_view, name='history_list'),
    path('history/detail/<int:history_id>/', views.history_detail_view, name='history_detail'),
    path('history/download/<int:history_id>/', views.download_history, name='download_history'),
    path('history/delete/', views.delete_history, name='delete_history'),

    # Profile & Auth
    path('profile/', views.profile, name='profile'),
    
    # URL untuk ganti password
    path('profile/password/', auth_views.PasswordChangeView.as_view(
        template_name='profile_password_change.html', # Nama file harus sesuai dengan file di folder templates
        success_url='/profile/' 
    ), name='password_change'),
    
    # URL notifikasi sukses ganti password
    path('profile/password/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='password_change_done.html' 
    ), name='password_change_done'),
]