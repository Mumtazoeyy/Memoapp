from django.urls import path
from . import views

urlpatterns = [
    # Main Reading List
    path('', views.reading_list, name='reading_list'),

    # Management
    path('add/', views.reading_add, name='reading_add'),
    path('edit/<int:pk>/', views.reading_edit, name='reading_edit'),
    path('edit-bulk/', views.reading_edit_bulk, name='reading_edit_bulk'),
    path('delete/<int:pk>/', views.reading_delete, name='reading_delete'),
    path('delete-selected/', views.delete_selected, name='delete_selected'),

    # Utility & Data
    path('search/', views.search_view, name='search'),
    path('import/', views.import_data, name='import_data'),
    path('export/', views.export_data, name='export_data'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('detail/<int:item_id>/', views.reading_item_detail, name='reading_item_detail'),
]