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

## Bringing existing data over

The companion does not auto-copy rows from `notifications_notification`
into `notifications_sites_notification`. The reasoning: there's no
correct default for which site a row should belong to, and a migration
that silently picks `SITE_ID` would be wrong for anyone running more
than one site. Two options:

**Start fresh.** Install the companion as documented above. Future
notifications land in `notifications_sites_notification`. Existing
rows stay in `notifications_notification` until you drop the table
yourself.

**Copy legacy rows over.** Run the SQL below in a transaction,
replacing `<your-default-site-id>` with the `Site` PK that
unassigned notifications should belong to. Drop the `COALESCE` if
your base table never had a `site_id` column (i.e. you were on plain
`django-notifications-community`, not Guillaume Libersat's
[`feature/sites-framework`](https://github.com/glibersat/django-notifications/tree/feature/sites-framework)
branch).

```sql
INSERT INTO notifications_sites_notification (
    level, recipient_id, unread,
    actor_content_type_id, actor_object_id, verb, description,
    target_content_type_id, target_object_id,
    action_object_content_type_id, action_object_object_id,
    timestamp, public, deleted, emailed, data,
    site_id
)
SELECT
    level, recipient_id, unread,
    actor_content_type_id, actor_object_id, verb, description,
    target_content_type_id, target_object_id,
    action_object_content_type_id, action_object_object_id,
    timestamp, public, deleted, emailed, data,
    COALESCE(site_id, <your-default-site-id>)
FROM notifications_notification;
```

## License

BSD-3-Clause. See [LICENSE.txt](LICENSE.txt).
