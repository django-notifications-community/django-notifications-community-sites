"""System checks for notifications_sites."""

from django.apps import apps
from django.conf import settings
from django.core.checks import Error


def check_sites_installed(app_configs, **kwargs):
    """``django.contrib.sites`` must be installed."""
    if apps.is_installed('django.contrib.sites'):
        return []
    return [
        Error(
            "'django.contrib.sites' is required by notifications_sites but not in INSTALLED_APPS.",
            hint="Add 'django.contrib.sites' to INSTALLED_APPS.",
            id='notifications_sites.E001',
        )
    ]


def check_site_id(app_configs, **kwargs):
    """``SITE_ID`` must be set so ``Site.objects.get_current()`` works."""
    if getattr(settings, 'SITE_ID', None):
        return []
    return [
        Error(
            'SITE_ID is not set.',
            hint=('Set SITE_ID to the primary key of the Site row that should own background-job notifications.'),
            id='notifications_sites.E002',
        )
    ]


def check_notification_model_setting(app_configs, **kwargs):
    """``NOTIFICATIONS_NOTIFICATION_MODEL`` must point at the companion model."""
    expected = 'notifications_sites.Notification'
    actual = getattr(settings, 'NOTIFICATIONS_NOTIFICATION_MODEL', 'notifications.Notification')
    if actual == expected:
        return []
    return [
        Error(
            f"NOTIFICATIONS_NOTIFICATION_MODEL is '{actual}'; expected '{expected}'.",
            hint=(
                f'Set NOTIFICATIONS_NOTIFICATION_MODEL = {expected!r} in '
                'settings.py so the companion model is the swap target. '
                'If you are subclassing notifications_sites.Notification with '
                'a custom concrete model, suppress this check via '
                "SILENCED_SYSTEM_CHECKS = ['notifications_sites.E003']."
            ),
            id='notifications_sites.E003',
        )
    ]


def check_app_ordering(app_configs, **kwargs):
    """``'notifications_sites'`` must come after ``'notifications'`` in INSTALLED_APPS.

    The companion's ``apps.ready()`` disconnects the base's notify_handler
    by ``dispatch_uid``. The base's ``ready()`` must run first or the
    disconnect is a no-op.
    """
    labels = list(apps.app_configs)
    try:
        notifications_idx = labels.index('notifications')
        sites_idx = labels.index('notifications_sites')
    except ValueError:
        return []  # other checks fire when either app is missing

    if sites_idx > notifications_idx:
        return []
    return [
        Error(
            "'notifications_sites' must come after 'notifications' in INSTALLED_APPS.",
            hint=(
                'Move notifications_sites below notifications in INSTALLED_APPS '
                "so the base's apps.ready() registers the default notify_handler "
                "before notifications_sites' apps.ready() replaces it."
            ),
            id='notifications_sites.E004',
        )
    ]
