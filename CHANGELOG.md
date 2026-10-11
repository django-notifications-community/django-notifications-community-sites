# Changelog

All notable changes to this project will be documented in this file.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.1.0 - 2026-10-11

- `site_aware_notify_handler` now delegates to the base `notify_handler`
  instead of carrying its own copy. It only fills in
  `Site.objects.get_current()` when neither `site=` nor `site_id=` was
  passed. Requires `django-notifications-community>=1.12.2`.
- `notify.send()` rejects model classes and unsaved instances for
  `sender`, `target` and `action_object`, as the base does.
- `notify.send(site_id=<pk>)` is accepted again; the base assigns it to
  the FK like any other field. Passing something other than a `Site`
  instance to `site=` now raises Django's `ValueError` instead of the
  companion's `TypeError`.
- Fix: `notify.send(..., data={...})` to a group, list or queryset of
  recipients kept the payload only for the first recipient. The old
  handler popped `data` inside the per recipient loop; the base splits
  kwargs once, so every recipient now gets it.
- Add migration 0003 recording `default_manager_name = 'objects'` from
  1.0.2. No schema change, but projects running `makemigrations --check`
  no longer see pending changes for `notifications_sites`.
- Tested on Python 3.14 and Django 6.1.

Migration 0003 is included; it records a Meta option and changes no
schema. Requires `django-notifications-community>=1.12.2`.

## 1.0.2 - 2026-04-30

- **Behavior change:** the registered queryset filter now resolves the current
  site by `Host` header first when a request is in scope, falling back to
  `SITE_ID` only when no `Site` row matches the host. This inverts Django's
  `Site.objects.get_current(request)`. Multi-tenant Django apps no longer
  silently route every request to the `SITE_ID` site. Request-less callers
  (background jobs, `has_notification`) still go through `SITE_ID`.
- Pin `Notification.Meta.default_manager_name = 'objects'` so
  `user.notifications` reverse-FKs don't double-filter by `SITE_ID` via the
  `CurrentSiteManager` and disagree with the new resolver.
- Fix: `notify.send(..., data={...})` no longer drops the caller's dict.
  The handler's data-merging loop set `newnotify.data` only to overwrite
  it on the trailing assignment; seed the merge dict with the explicit
  `data=` payload so it survives and merges with arbitrary extras.
- Add `--database` to `copy_legacy_notifications`. The command now
  routes through `connections[alias]`, so projects using
  `DATABASE_ROUTERS` to push notifications onto a non-default alias can
  copy legacy rows on the right database instead of silently hitting
  `default`.
- `copy_legacy_notifications` validates the source schema up front. A
  legacy table missing any column the command needs now raises
  `CommandError` naming the missing columns instead of failing
  mid-INSERT with a cryptic `OperationalError`.
- Validate `site=` up front in `site_aware_notify_handler`. Passing
  `site=<int_pk>` or `site=<str>` now raises `TypeError` with a hint
  pointing at `Site.objects.get(pk=...)`, mirroring the existing
  `site_id=` guard.
- `notify.send(..., timestamp=None)` is now coerced to `timezone.now()`
  instead of raising `IntegrityError` on the `NOT NULL` column. Aligns
  the companion handler with base `notify_handler` (the base shipped
  the same fix in [PR #57](https://github.com/django-notifications-community/django-notifications-community/pull/57)).
- Wheel size: exclude `notifications_sites.tests` from the built
  wheel via `include-package-data = false` plus an `exclude` pattern.
  ~30 KB of test code no longer ships to installs.

## 1.0.1 - 2026-04-30

- Widen `Notification.id` to `BigAutoField` (migration 0002).
- `notify.send(site_id=...)` now raises `TypeError`. Pass a `Site` via `site=`.
- Raise `ImproperlyConfigured` if the base `notify_handler` disconnect fails.
- `copy_legacy_notifications` resolves the target table via `Notification._meta.db_table`.
- Drop the false cache-invalidation hook claim from the docs.
- Document the `Site.objects.get_current()` fallback for request-less callers.
- Bump build floor to `setuptools>=77`; pin `django-notifications-community<2`.

## 1.0.0

- Initial release. Concrete `Notification` model with non-nullable
  `site` FK, site-aware notify handler, admin override, and system
  checks. Plugs into `django-notifications-community`'s registry hooks.
- Ships an opt-in `copy_legacy_notifications` management command for
  users upgrading from a base-only or feature-branch install. Idempotent
  by default (refuses to copy when the target already has rows unless
  `--force`), with `--dry-run` and an explicit `--default-site` to
  avoid silent assumptions.
