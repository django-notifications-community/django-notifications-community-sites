"""Concrete Notification model with a non-nullable site FK."""

from django.contrib.sites.managers import CurrentSiteManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from notifications.base.models import AbstractNotification, NotificationQuerySet
from notifications.swappable import NOTIFICATION_MODEL_SETTING

_NotificationOnSiteManagerBase = CurrentSiteManager.from_queryset(NotificationQuerySet)


class NotificationOnSiteManager(_NotificationOnSiteManagerBase):
    """CurrentSiteManager paired with NotificationQuerySet methods.

    Subclassed (rather than aliased to ``CurrentSiteManager.from_queryset(...)``)
    so that ``makemigrations`` records a stable import path for the manager.
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
        indexes = [
            *AbstractNotification.Meta.indexes,
            models.Index(fields=['site', 'recipient', 'unread']),
        ]
