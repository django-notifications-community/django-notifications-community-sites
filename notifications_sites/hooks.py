"""Hook callbacks plugged into ``notifications.registry``."""

from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site


def _resolve_site(request=None):
    """Return the current site, falling back to SITE_ID when no request is available."""
    if request is not None:
        return get_current_site(request)
    return Site.objects.get_current()


def filter_by_current_site(queryset, request):
    """Restrict ``queryset`` to the current site.

    Plugged in via ``notifications.registry.register_queryset_filter``,
    so it runs wherever the base builds a Notification queryset (list
    views, mark/delete views, JSON endpoints, the unread badge, and the
    ``has_notification`` filter).
    """
    return queryset.filter(site=_resolve_site(request))


def site_aware_cache_key(base_key, user, request=None):
    """Append the current site PK to the unread-count cache key.

    Without this, two sites served from the same project would poison
    each other's cached unread counts.
    """
    return f'{base_key}_site_{_resolve_site(request).pk}'
