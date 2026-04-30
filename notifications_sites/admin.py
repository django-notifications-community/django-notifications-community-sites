"""Admin override that includes the ``site`` column."""

from django.contrib import admin
from notifications.admin import NotificationAdmin as BaseNotificationAdmin
from notifications.swappable import load_notification_model


class NotificationAdmin(BaseNotificationAdmin):
    """Adds ``site`` to ``list_display`` and ``list_filter``."""

    def get_list_display(self, request):
        return [*super().get_list_display(request), 'site']

    def get_list_filter(self, request):
        return [*super().get_list_filter(request), 'site']


Notification = load_notification_model()

# The base's admin.py registered the resolved Notification with the
# sites-blind admin. Replace it with our subclass.
if Notification in admin.site._registry:
    admin.site.unregister(Notification)
admin.site.register(Notification, NotificationAdmin)
