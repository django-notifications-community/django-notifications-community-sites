# Changelog

All notable changes to this project will be documented in this file.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
