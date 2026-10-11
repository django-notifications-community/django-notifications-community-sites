"""Test settings for notifications_sites."""

SECRET_KEY = 'secret_key'

DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'test.sqlite3',
    },
    # Second alias used by CopyLegacyNotificationsDatabaseFlagTest. Other
    # tests do not list 'aux' in their TestCase.databases set, so the
    # connection is only opened/migrated for that one case.
    'aux': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'test_aux.sqlite3',
    },
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
    'notifications',
    'notifications_sites',
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

DJANGO_NOTIFICATIONS_CONFIG = {
    'USE_JSONFIELD': True,
}
USE_TZ = True

SITE_ID = 1

NOTIFICATIONS_NOTIFICATION_MODEL = 'notifications_sites.Notification'
