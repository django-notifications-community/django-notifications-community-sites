"""Test settings for notifications_sites."""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SECRET_KEY = 'secret_key'

DEBUG = True
TESTING = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'test.sqlite3',
    }
}

MIDDLEWARE = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sessions',
    'django.contrib.sites',
    'notifications_sites.tests.test_models',
    'notifications',
]

ROOT_URLCONF = 'notifications_sites.tests.urls'
STATIC_URL = '/static/'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'OPTIONS': {
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

LOGIN_URL = '/admin/login/'
APPEND_SLASH = True

DJANGO_NOTIFICATIONS_CONFIG = {
    'USE_JSONFIELD': True,
}
USE_TZ = True

SITE_ID = 1

ALLOWED_HOSTS = []
# notifications_sites.tests.test_models has no app config so we set this here.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
