"""App config for notifications_sites."""

from django.apps import AppConfig
from django.core.checks import register
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _


class Config(AppConfig):
    name = 'notifications_sites'
    label = 'notifications_sites'
    verbose_name = _('Notifications (multi-site)')
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        super().ready()

        from notifications.registry import (
            register_cache_key_modifier,
            register_queryset_filter,
        )
        from notifications.signals import notify

        from notifications_sites.checks import (
            check_app_ordering,
            check_notification_model_setting,
            check_site_id,
            check_sites_installed,
        )
        from notifications_sites.handlers import site_aware_notify_handler
        from notifications_sites.hooks import (
            filter_by_current_site,
            site_aware_cache_key,
        )

        # Replace the base's notify_handler with the site-aware variant.
        # Requires this app to come AFTER 'notifications' in INSTALLED_APPS
        # so the base's connect() has already run; check_app_ordering enforces it.
        disconnected = notify.disconnect(dispatch_uid='notifications.models.notification')
        if not disconnected:
            raise ImproperlyConfigured(
                'notifications_sites failed to disconnect the base notify_handler. '
                "Ensure 'notifications_sites' comes after 'notifications' in "
                "INSTALLED_APPS. If the base package's dispatch_uid has changed, "
                'this companion needs an update.'
            )
        notify.connect(site_aware_notify_handler, dispatch_uid='notifications_sites.notification')

        register_queryset_filter(filter_by_current_site)
        register_cache_key_modifier(site_aware_cache_key)

        register(check_sites_installed)
        register(check_site_id)
        register(check_notification_model_setting)
        register(check_app_ordering)
