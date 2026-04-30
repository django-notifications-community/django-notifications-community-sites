"""App config for notifications_sites."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class Config(AppConfig):
    name = 'notifications_sites'
    label = 'notifications_sites'
    verbose_name = _('Notifications (multi-site)')
    default_auto_field = 'django.db.models.AutoField'
