"""Concrete Notification model with a non-nullable site FK."""

from django.contrib.sites.managers import CurrentSiteManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from notifications.base.models import AbstractNotification, NotificationQuerySet
from notifications.swappable import NOTIFICATION_MODEL_SETTING

_NotificationOnSiteManagerBase = CurrentSiteManager.from_queryset(NotificationQuerySet)


class NotificationOnSiteManager(_NotificationOnSiteManagerBase):
    """CurrentSiteManager paired with NotificationQuerySet methods.

    Defined as a real subclass so the migration references this name
    instead of a synthetic class produced by ``from_queryset``.
    """


class Notification(AbstractNotification):
    site = models.ForeignKey(
        'sites.Site',
        verbose_name=_('site'),
        related_name='+',
        on_delete=models.CASCADE,
    )

    on_site = NotificationOnSiteManager()

    class Meta(AbstractNotification.Meta):
        abstract = False
        swappable = NOTIFICATION_MODEL_SETTING
        # ``user.notifications`` uses the model's default manager, which would
        # otherwise be the CurrentSiteManager (it sorts first by creation order
        # in subclasses). That silently pre-filters by ``SITE_ID``, double-
        # filtering with the registered queryset hook and disagreeing with it
        # when the request host resolves to a different site. Pin the default
        # to ``objects`` so the hook is the only filter.
        default_manager_name = 'objects'
        indexes = [
            *AbstractNotification.Meta.indexes,
            models.Index(fields=['site', 'recipient', 'unread']),
        ]
