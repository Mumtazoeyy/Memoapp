from pathlib import Path
import os
from django.contrib.messages import constants as messages

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# --- EDIT BAGIAN INI ---
# 1. Pastikan SECRET_KEY aman (jangan pernah share di GitHub publik jika memungkinkan)
SECRET_KEY = 'django-insecure-(bb@92zfquvn7j*510%cqnsj5nsx4=cmb3+waz%zbq+fsfpp&b'

# 2. Ubah DEBUG menjadi False untuk produksi
DEBUG = True
ALLOWED_HOSTS = ['*']  # Ini lebih mudah untuk development
##ALLOWED_HOSTS = ['MintChocolatte.pythonanywhere.com', '127.0.0.1']
# -----------------------

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app_1',
    'django.contrib.sites',
    'django.contrib.sitemaps',
]

SITE_ID = 1

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mysite.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'app_1' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mysite.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = []

# Internationalization
LANGUAGE_CODE = 'id-ID'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_TZ = True

# Static & Media files
STATIC_URL = 'static/'
# --- TAMBAHKAN INI ---
STATIC_ROOT = BASE_DIR / 'static'
# ---------------------
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Configuration settings
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

# Authentication Redirects
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'reading_list'
LOGOUT_REDIRECT_URL = 'login'

# Bootstrap-friendly message tags
MESSAGE_TAGS = {
    messages.SUCCESS: 'success',
    messages.ERROR: 'danger',
    messages.WARNING: 'warning',
    messages.INFO: 'info',
}