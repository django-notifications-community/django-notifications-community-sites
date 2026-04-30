# Changelog

All notable changes to this project will be documented in this file.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Initial release. Concrete `Notification` model with non-nullable
  `site` FK, site-aware notify handler, admin override, and system
  checks. Plugs into `django-notifications-community`'s registry hooks.
- Ships an opt-in `copy_legacy_notifications` management command for
  users upgrading from a base-only or feature-branch install. Idempotent
  by default (refuses to copy when the target already has rows unless
  `--force`), with `--dry-run` and an explicit `--default-site` to
  avoid silent assumptions.
