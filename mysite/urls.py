from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from app_1 import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 1. Halaman utama (home)
    path('', views.home_master, name='home'), 
    
    # 2. Rute Login & Register langsung di root (domain.com/login/)
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    
    # 3. Rute fitur Reading List
    path('reading/', include('app_1.urls')), 
]

# Konfigurasi media
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)