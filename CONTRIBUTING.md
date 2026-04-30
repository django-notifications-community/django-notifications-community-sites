# Contributing

Thanks for your interest in helping maintain `django-notifications-community-sites`.
This is the multi-site companion to
[`django-notifications-community`](https://github.com/django-notifications-community/django-notifications-community);
contributions are welcome, especially:

- Bug reports and fixes against current Django and Python versions
- Improvements to system checks and migration ergonomics
- CI, packaging, and documentation improvements

## Development setup

We use [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
git clone https://github.com/django-notifications-community/django-notifications-community-sites
cd django-notifications-community-sites
uv sync
uv run pre-commit install
```

If you're working from a local checkout of the base package, install it as
editable so changes flow through:

```bash
uv pip install -e ../django-notifications-community
```

The pre-commit hooks run [ruff](https://docs.astral.sh/ruff/) (lint + format
in check mode) on every commit so issues get caught before they reach CI.

## Running tests

The full CI matrix runs via `tox`:

```bash
tox                     # all envs
tox -e py312-django52   # a single env
```

You can also run a quick single-version check without tox:

```bash
uv run python manage.py test
```

Tests live in `notifications_sites/tests/` and use Django's built-in test runner.

## Opening a pull request

- Fork the repo and create a topic branch off `master`.
- Keep PRs focused. One idea per PR is easier to review and less risky to revert.
- Add or update tests for any behavior change.
- Update `CHANGELOG.md` under an "Unreleased" section at the top if the change
  is user-visible.
- Make sure `tox` passes locally before pushing.
- Squash fixup commits before requesting review.

## Releases

Releases are cut by maintainers by tagging `vX.Y.Z` on `master`. The release
workflow publishes to PyPI via Trusted Publishing, gated on a manual approval
in the `pypi` GitHub environment. No API tokens are stored in the repository.
