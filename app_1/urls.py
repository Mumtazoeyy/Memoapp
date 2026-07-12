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

    path('manage/', views.manage_view, name='manage'),  
    path('sync-item-detail/<int:user_id>/', views.sync_item_detail, name='sync_item_detail'),

    path('library/', views.library_view, name='library'),
    path('library/results/', views.library_results, name='library_results'),
    path('item/<int:pk>/', views.item_detail_view, name='item_detail'),
    path('library/item/<int:pk>/', views.library_item_detail, name='library_item_detail'),
    path('library/add-to-list/<int:pk>/', views.add_to_reading_list, name='add_to_reading_list'),
    path('library/remove-from-list/<int:pk>/', views.remove_from_reading_list, name='remove_from_reading_list'),

    # Profile & Auth
    path('profile/', views.profile, name='profile'),
    
]