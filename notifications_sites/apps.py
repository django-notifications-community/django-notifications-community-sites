"""App config for notifications_sites."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class Config(AppConfig):
    name = 'notifications_sites'
    label = 'notifications_sites'
    verbose_name = _('Notifications (multi-site)')
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        super().ready()

        from notifications.registry import (
            register_cache_key_modifier,
            register_queryset_filter,
        )
        from notifications.signals import notify

        from notifications_sites.handlers import site_aware_notify_handler
        from notifications_sites.hooks import (
            filter_by_current_site,
            site_aware_cache_key,
        )

        # Replace the base's notify_handler with the site-aware variant.
        # Requires this app to come AFTER 'notifications' in INSTALLED_APPS
        # so the base's connect() has already run.
        notify.disconnect(dispatch_uid='notifications.models.notification')
        notify.connect(site_aware_notify_handler, dispatch_uid='notifications_sites.notification')

        register_queryset_filter(filter_by_current_site)
        register_cache_key_modifier(site_aware_cache_key)
