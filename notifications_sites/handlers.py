"""Site-aware replacement for the base ``notify_handler``.

Supplies ``site = Site.objects.get_current()`` when the caller passed
neither ``site`` nor ``site_id``, then defers to the base handler, which
assigns both as concrete model fields (base >= 1.12.2) and performs all
other validation. ``apps.ready()`` swaps this in for the base handler.
"""

from django.contrib.sites.models import Site
from notifications.base.models import notify_handler


def site_aware_notify_handler(verb, **kwargs):
    if kwargs.get('site') is None and 'site_id' not in kwargs:
        kwargs['site'] = Site.objects.get_current()
    return notify_handler(verb, **kwargs)
