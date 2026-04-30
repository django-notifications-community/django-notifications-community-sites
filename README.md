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
`NOTIFICATIONS_NOTIFICATION_MODEL` must point at the companion model;
the system check will tell you if it doesn't (silence with
`SILENCED_SYSTEM_CHECKS = ['notifications_sites.E003']` if you're
subclassing the companion).

## How it works

This package registers callbacks against the base's `notifications.registry`
extension hooks:

- A queryset filter that adds `.filter(site=current_site)` wherever the base
  builds a Notification queryset.
- A cache-key modifier that namespaces the unread-count cache key by site, so
  concurrent sites don't poison each other.

The base's `notify_handler` is replaced with a site-aware variant that stamps
`Site.objects.get_current()` on each notification (or whatever you pass via
`site=...`).

The base's views, helpers, and template tags are reused unchanged through the
hooks. No URL or template changes required.

### Background jobs and other request-less callers

When `notify.send()` fires from a code path without a request,
`Site.objects.get_current()` falls back to the row whose primary key matches
`SITE_ID`. In a multi-tenant deployment that is rarely the right answer for
tenant N. Pass `site=` explicitly from background jobs:

```python
notify.send(actor, recipient=user, verb='ping', site=tenant_site)
```

### Request host wins over `SITE_ID`

When a request is in scope, the companion resolves the current site by `Host`
header first, falling back to `SITE_ID` only if no `Site` row matches. This
inverts Django's own `Site.objects.get_current(request)`, which checks
`SITE_ID` before host. The companion's choice fits multi-tenant Django apps:
each request gets the site it came from; background jobs and other request-less
callers fall back to `SITE_ID`.

Practical implications:

- Every tenant domain needs a `Site` row.
- Hosts that don't match any row (e.g. `testserver`, `localhost` in dev) fall
  back to the `SITE_ID`-resolved row, so tests and local development keep
  working without per-host setup.
- If you change `SITE_ID` mid-process, call `Site.objects.clear_cache()`
  afterwards or the cached lookup will keep returning the previously-resolved
  row.

## Bringing existing data over

The companion does not auto-copy rows from `notifications_notification`
into `notifications_sites_notification`. The reasoning: there's no
correct default for which site a legacy row should belong to, and a
migration that silently picks `SITE_ID` would be wrong for anyone
running more than one site. Two options:

**Start fresh.** Install the companion as documented above. Future
notifications land in `notifications_sites_notification`. Existing
rows stay in `notifications_notification` until you drop the table
yourself.

**Copy legacy rows over with the bundled command.** Run:

```bash
python manage.py copy_legacy_notifications --default-site=<pk>
```

`<pk>` is the `Site` primary key to assign to rows whose `site_id` is
`NULL`, or to every row when the source table has no `site_id` column
at all (i.e. you were on plain `django-notifications-community`, not
Guillaume Libersat's
[`feature/sites-framework`](https://github.com/glibersat/django-notifications/tree/feature/sites-framework)
branch). Existing `site_id` values are preserved.

Useful flags:

- `--dry-run` — report what would be copied without writing.
- `--force` — copy even if `notifications_sites_notification` already
  has rows (off by default to avoid duplicates).

The copy runs in a single transaction. After verifying everything
landed, you can drop `notifications_notification` yourself.

## License

BSD-3-Clause. See [LICENSE.txt](LICENSE.txt).
