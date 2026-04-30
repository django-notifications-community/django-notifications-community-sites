# django-notifications-community-sites

[![PyPI](https://img.shields.io/pypi/v/django-notifications-community-sites.svg)](https://pypi.org/project/django-notifications-community-sites/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-notifications-community-sites.svg)](https://pypi.org/project/django-notifications-community-sites/)
[![Django versions](https://img.shields.io/pypi/djversions/django-notifications-community-sites.svg?label=django)](https://pypi.org/project/django-notifications-community-sites/)

Multi-site companion to
[`django-notifications-community`](https://github.com/django-notifications-community/django-notifications-community).

Adds a non-nullable `site` FK on each notification, a site-aware notify handler
that stamps `Site.objects.get_current()` automatically, and a queryset filter
that scopes views and the unread badge to the current site.

## Why this exists

The base package is sites-blind by design, so installing it imposes no
dependency on `django.contrib.sites`. If you do run more than one site from a
single project (different domains, different `SITE_ID`), install this companion
to keep notifications generated on one site from leaking to another.

## Installation

Either install the base with the `sites` extra:

```bash
pip install "django-notifications-community[sites]"
```

or install this package directly (it pulls the base in as a dependency):

```bash
pip install django-notifications-community-sites
```

## Setup

In `settings.py`:

```python
INSTALLED_APPS = [
    ...,
    'django.contrib.sites',
    'notifications',
    'notifications_sites',   # must come AFTER 'notifications'
]

NOTIFICATIONS_NOTIFICATION_MODEL = 'notifications_sites.Notification'

SITE_ID = 1
```

Then run migrations:

```bash
python manage.py migrate
```

`SITE_ID` is required; the system check will tell you if it's missing.

## How it works

This package registers callbacks against the base's `notifications.registry`
extension hooks:

- A queryset filter that adds `.filter(site=current_site)` wherever the base
  builds a Notification queryset.
- A cache-key modifier that namespaces the unread-count cache key by site, so
  concurrent sites don't poison each other.
- A cache-invalidation registration that drops all per-site cache variants on
  mutation.

The base's `notify_handler` is replaced with a site-aware variant that stamps
`Site.objects.get_current()` on each notification (or whatever you pass via
`site=...`).

The base's views, helpers, and template tags are reused unchanged through the
hooks. No URL or template changes required.

## Migrating from the feature branch

If you were previously running on the unmerged `feature/sites-framework`
branch of `django-notifications-community`, your existing rows live in
`notifications_notification`. The companion's second migration copies them
into `notifications_sites_notification` and falls back to `SITE_ID` for any
row whose `site` was `NULL`.

## License

BSD-3-Clause. See [LICENSE.txt](LICENSE.txt).
