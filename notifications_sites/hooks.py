"""Hook callbacks plugged into ``notifications.registry``."""

from django.contrib.sites.models import Site


def _resolve_site(request=None):
    """Return the current site for ``request``, falling back to ``SITE_ID``.

    For request-bound calls we resolve by ``Host`` header first, so multi-tenant
    Django apps see the right ``Site`` per request. Django's own
    ``Site.objects.get_current(request)`` checks ``SITE_ID`` first and only falls
    back to host resolution when it is unset, which is the wrong default for a
    package whose entire purpose is multi-site routing.

    If no ``Site`` row matches the request's host, fall back to the
    ``SITE_ID``-resolved row instead of raising. That keeps things sane for
    development hosts like ``testserver`` and for misconfigured tenants while
    still giving a working default.
    """
    if request is not None:
        try:
            return Site.objects._get_site_by_request(request)
        except Site.DoesNotExist:
            pass
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
