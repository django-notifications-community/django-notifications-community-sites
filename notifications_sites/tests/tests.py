"""Tests for notifications_sites."""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from notifications.signals import notify
from notifications.swappable import load_notification_model
from notifications.templatetags.notifications_tags import (
    get_cached_notification_unread_count,
    has_notification,
    unread_count_cache_key,
)

from notifications_sites.admin import NotificationAdmin
from notifications_sites.checks import (
    check_app_ordering,
    check_notification_model_setting,
    check_site_id,
    check_sites_installed,
)
from notifications_sites.hooks import _resolve_site
from notifications_sites.management.commands.copy_legacy_notifications import BASE_COLS

Notification = load_notification_model()


def unread_key(user, site):
    return f'notifications_unread_count_{user.pk}_site_{site.pk}'


class SiteTestCase(TestCase):
    """Two users and two sites, with the site and unread-count caches cleared."""

    def setUp(self):
        Site.objects.clear_cache()
        cache.clear()
        self.from_user = User.objects.create_user(username='from', password='pwd')
        self.to_user = User.objects.create_user(username='to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')


class NotifyHandlerSiteStampingTest(SiteTestCase):
    """The site-aware notify_handler stamps each notification with a site."""

    def test_default_site_from_site_id(self):
        notify.send(self.from_user, recipient=self.to_user, verb='pinged')
        n = Notification.objects.get(recipient=self.to_user)
        self.assertEqual(n.site_id, self.site_a.pk)

    def test_explicit_site_kwarg_overrides(self):
        notify.send(self.from_user, recipient=self.to_user, verb='pinged', site=self.site_b)
        n = Notification.objects.get(recipient=self.to_user)
        self.assertEqual(n.site_id, self.site_b.pk)

    @override_settings(SITE_ID=2)
    def test_default_follows_current_site_id(self):
        Site.objects.clear_cache()
        notify.send(self.from_user, recipient=self.to_user, verb='pinged')
        n = Notification.objects.get(recipient=self.to_user)
        self.assertEqual(n.site_id, self.site_b.pk)

    def test_site_id_kwarg_is_accepted(self):
        """The base handler assigns attnames, so site_id= lands on the FK like site= does."""
        notify.send(self.from_user, recipient=self.to_user, verb='pinged', site_id=self.site_b.pk)
        n = Notification.objects.get(recipient=self.to_user)
        self.assertEqual(n.site_id, self.site_b.pk)

    def test_non_site_value_for_site_is_rejected(self):
        """Django's FK descriptor refuses anything that is not a Site instance."""
        for bad in (self.site_b.pk, 'b.example.com'):
            with self.subTest(site=bad), self.assertRaises(ValueError):
                notify.send(self.from_user, recipient=self.to_user, verb='pinged', site=bad)

    def test_sender_class_is_rejected(self):
        """A model class instead of an instance must raise, not store the descriptor repr."""
        with self.assertRaises(TypeError):
            notify.send(User, recipient=self.to_user, verb='pinged')

    def test_extra_kwargs_merge_into_data(self):
        """Smoke test that delegation passes data= and free-form kwargs through to the base."""
        notify.send(self.from_user, recipient=self.to_user, verb='dk', data={'foo': 'bar'}, extra='zzz')
        n = Notification.objects.get(verb='dk')
        self.assertEqual(n.data, {'foo': 'bar', 'extra': 'zzz'})


class ViewFilteringTest(SiteTestCase):
    """Base views filter by the current site via the registered hook."""

    def setUp(self):
        super().setUp()
        notify.send(self.from_user, recipient=self.to_user, verb='a1', site=self.site_a)
        notify.send(self.from_user, recipient=self.to_user, verb='a2', site=self.site_a)
        notify.send(self.from_user, recipient=self.to_user, verb='b1', site=self.site_b)
        self.client.force_login(self.to_user)

    def test_all_view_filters_by_current_site(self):
        response = self.client.get(reverse('notifications:all'))
        notifications = list(response.context['notifications'])
        self.assertSetEqual({n.verb for n in notifications}, {'a1', 'a2'})

    @override_settings(SITE_ID=2)
    def test_unread_view_on_other_site(self):
        Site.objects.clear_cache()
        response = self.client.get(reverse('notifications:unread'))
        notifications = list(response.context['notifications'])
        self.assertEqual([n.verb for n in notifications], ['b1'])

    def test_mark_as_read_scoped_to_current_site(self):
        n_b = Notification.objects.get(verb='b1')
        response = self.client.post(reverse('notifications:mark_as_read', kwargs={'slug': n_b.slug}))
        self.assertEqual(response.status_code, 404)
        n_b.refresh_from_db()
        self.assertTrue(n_b.unread)

    def test_mark_as_read_succeeds_on_same_site(self):
        n_a = Notification.objects.filter(verb='a1').first()
        response = self.client.post(reverse('notifications:mark_as_read', kwargs={'slug': n_a.slug}))
        self.assertEqual(response.status_code, 302)
        n_a.refresh_from_db()
        self.assertFalse(n_a.unread)

    def test_mark_all_as_read_scoped_to_current_site(self):
        self.client.post(reverse('notifications:mark_all_as_read'))
        site_a_unread = Notification.objects.filter(site=self.site_a, unread=True).count()
        site_b_unread = Notification.objects.filter(site=self.site_b, unread=True).count()
        self.assertEqual(site_a_unread, 0)
        self.assertEqual(site_b_unread, 1)

    def test_delete_scoped_to_current_site(self):
        n_b = Notification.objects.get(verb='b1')
        response = self.client.post(reverse('notifications:delete', kwargs={'slug': n_b.slug}))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Notification.objects.filter(pk=n_b.pk).exists())

    def test_live_unread_count_filters_by_site(self):
        response = self.client.get(reverse('notifications:live_unread_notification_count'))
        self.assertEqual(response.json()['unread_count'], 2)

    @override_settings(SITE_ID=2)
    def test_live_unread_count_on_other_site(self):
        Site.objects.clear_cache()
        response = self.client.get(reverse('notifications:live_unread_notification_count'))
        self.assertEqual(response.json()['unread_count'], 1)

    def test_live_unread_list_filters_by_site(self):
        response = self.client.get(reverse('notifications:live_unread_notification_list'))
        data = response.json()
        self.assertEqual(data['unread_count'], 2)
        self.assertEqual({n['verb'] for n in data['unread_list']}, {'a1', 'a2'})

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_request_host_picks_site_over_site_id(self):
        """SITE_ID=1 (site_a), but the request comes from site_b's domain → site_b wins."""
        response = self.client.get(reverse('notifications:all'), HTTP_HOST='b.example.com')
        verbs = {n.verb for n in response.context['notifications']}
        self.assertEqual(verbs, {'b1'})

    def test_unmatched_host_falls_back_to_site_id(self):
        """No Site row for 'testserver' → fall through to SITE_ID=1 → site_a."""
        response = self.client.get(reverse('notifications:all'))
        verbs = {n.verb for n in response.context['notifications']}
        self.assertEqual(verbs, {'a1', 'a2'})


@override_settings(ALLOWED_HOSTS=['*'])
class ResolveSiteTest(SiteTestCase):
    """The hooks resolver prefers request host with SITE_ID as the request-less fallback."""

    def test_no_request_uses_site_id(self):
        self.assertEqual(_resolve_site().pk, self.site_a.pk)

    def test_request_host_takes_precedence_over_site_id(self):
        req = RequestFactory().get('/', HTTP_HOST='b.example.com')
        self.assertEqual(_resolve_site(req).pk, self.site_b.pk)

    def test_request_host_with_port_strips_and_matches(self):
        req = RequestFactory().get('/', HTTP_HOST='b.example.com:8000')
        self.assertEqual(_resolve_site(req).pk, self.site_b.pk)

    def test_unmatched_host_falls_back_to_site_id(self):
        req = RequestFactory().get('/', HTTP_HOST='nope.example.com')
        self.assertEqual(_resolve_site(req).pk, self.site_a.pk)


class CacheKeyNamespacingTest(SiteTestCase):
    """Each site has its own unread-count cache key."""

    def test_cache_key_includes_site_pk(self):
        self.assertEqual(unread_count_cache_key(self.to_user), unread_key(self.to_user, self.site_a))

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'CACHE_TIMEOUT': 60, 'USE_JSONFIELD': True})
    def test_concurrent_site_caches_do_not_collide(self):
        notify.send(self.from_user, recipient=self.to_user, verb='a', site=self.site_a)
        notify.send(self.from_user, recipient=self.to_user, verb='b', site=self.site_b)

        with override_settings(SITE_ID=self.site_a.pk):
            Site.objects.clear_cache()
            count_a = get_cached_notification_unread_count(self.to_user)
        with override_settings(SITE_ID=self.site_b.pk):
            Site.objects.clear_cache()
            count_b = get_cached_notification_unread_count(self.to_user)

        self.assertEqual(count_a, 1)
        self.assertEqual(count_b, 1)
        self.assertEqual(cache.get(unread_key(self.to_user, self.site_a)), 1)
        self.assertEqual(cache.get(unread_key(self.to_user, self.site_b)), 1)

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'CACHE_TIMEOUT': 60, 'USE_JSONFIELD': True})
    def test_mark_as_read_invalidates_current_site_cache(self):
        notify.send(self.from_user, recipient=self.to_user, verb='a', site=self.site_a)
        get_cached_notification_unread_count(self.to_user)
        key_a = unread_key(self.to_user, self.site_a)
        self.assertEqual(cache.get(key_a), 1)

        n = Notification.objects.first()
        self.client.force_login(self.to_user)
        self.client.post(reverse('notifications:mark_as_read', kwargs={'slug': n.slug}))
        self.assertIsNone(cache.get(key_a))


class AdminTest(TestCase):
    """The companion admin includes the site column."""

    def test_list_display_includes_site(self):
        adm = NotificationAdmin(Notification, None)
        self.assertIn('site', adm.get_list_display(None))

    def test_list_filter_includes_site(self):
        adm = NotificationAdmin(Notification, None)
        self.assertIn('site', adm.get_list_filter(None))


class SystemCheckTest(TestCase):
    """System checks fire on misconfiguration and pass when configured correctly."""

    def test_sites_installed_passes(self):
        self.assertEqual(check_sites_installed(None), [])

    @override_settings(INSTALLED_APPS=[a for a in settings.INSTALLED_APPS if a != 'django.contrib.sites'])
    def test_sites_installed_errors(self):
        errors = check_sites_installed(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E001')

    def test_site_id_passes(self):
        self.assertEqual(check_site_id(None), [])

    @override_settings(SITE_ID=None)
    def test_site_id_errors_when_unset(self):
        errors = check_site_id(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E002')

    def test_notification_model_setting_passes(self):
        self.assertEqual(check_notification_model_setting(None), [])

    @override_settings(NOTIFICATIONS_NOTIFICATION_MODEL='myapp.MyNotification')
    def test_notification_model_setting_errors_on_mismatch(self):
        errors = check_notification_model_setting(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E003')

    def test_app_ordering_passes(self):
        self.assertEqual(check_app_ordering(None), [])

    def test_app_ordering_errors_when_misordered(self):
        fake_configs = {
            'admin': None,
            'notifications_sites': None,
            'notifications': None,
        }
        with patch('notifications_sites.checks.apps.app_configs', fake_configs):
            errors = check_app_ordering(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E004')


# Column DDL of the legacy notifications_notification table, as the base
# package's standard migration produces it on SQLite.
LEGACY_COLUMNS = {
    'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
    'level': "VARCHAR(20) NOT NULL DEFAULT 'info'",
    'recipient_id': 'INTEGER NOT NULL',
    'unread': 'BOOLEAN NOT NULL DEFAULT 1',
    'actor_content_type_id': 'INTEGER NOT NULL',
    'actor_object_id': 'VARCHAR(255) NOT NULL',
    'verb': 'VARCHAR(255) NOT NULL',
    'description': 'TEXT',
    'target_content_type_id': 'INTEGER',
    'target_object_id': 'VARCHAR(255)',
    'action_object_content_type_id': 'INTEGER',
    'action_object_object_id': 'VARCHAR(255)',
    'timestamp': 'DATETIME NOT NULL',
    'public': 'BOOLEAN NOT NULL DEFAULT 1',
    'deleted': 'BOOLEAN NOT NULL DEFAULT 0',
    'emailed': 'BOOLEAN NOT NULL DEFAULT 0',
    'data': 'TEXT',
}


class LegacyTableMixin:
    """Helpers to build and fill a legacy notifications_notification table on any alias."""

    def create_legacy_table(self, alias='default', columns=LEGACY_COLUMNS, with_site_column=False):
        columns = dict(columns)
        if with_site_column:
            columns['site_id'] = 'INTEGER'
        ddl = ', '.join(f'{name} {spec}' for name, spec in columns.items())
        with connections[alias].cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS notifications_notification')
            cursor.execute(f'CREATE TABLE notifications_notification ({ddl})')
        self.addCleanup(self.drop_legacy_table, alias)

    def drop_legacy_table(self, alias):
        with connections[alias].cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS notifications_notification')

    def insert_legacy_row(
        self, verb, alias='default', columns=BASE_COLS, with_site_column=False, site_id=None, recipient=None, actor=None
    ):
        recipient = recipient or self.to_user
        actor = actor or self.from_user
        ct = ContentType.objects.db_manager(alias).get_for_model(User)
        values = {
            'level': 'info',
            'recipient_id': recipient.pk,
            'unread': True,
            'actor_content_type_id': ct.pk,
            'actor_object_id': str(actor.pk),
            'verb': verb,
            'description': None,
            'target_content_type_id': None,
            'target_object_id': None,
            'action_object_content_type_id': None,
            'action_object_object_id': None,
            'timestamp': timezone.now(),
            'public': True,
            'deleted': False,
            'emailed': False,
            'data': None,
        }
        cols = list(columns)
        if with_site_column:
            cols.append('site_id')
            values['site_id'] = site_id
        placeholders = ', '.join(['%s'] * len(cols))
        with connections[alias].cursor() as cursor:
            cursor.execute(
                f'INSERT INTO notifications_notification ({", ".join(cols)}) VALUES ({placeholders})',
                [values[c] for c in cols],
            )


class CopyLegacyNotificationsCommandTest(LegacyTableMixin, SiteTestCase):
    """Opt-in management command to migrate legacy notifications_notification rows."""

    def test_noop_when_source_table_missing(self):
        out = StringIO()
        call_command('copy_legacy_notifications', stdout=out)
        self.assertIn('nothing to copy', out.getvalue().lower())
        self.assertEqual(Notification.objects.count(), 0)

    def test_noop_when_source_empty(self):
        self.create_legacy_table()
        out = StringIO()
        call_command('copy_legacy_notifications', stdout=out)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertIn('nothing to copy', out.getvalue().lower())

    def test_copies_rows_with_default_site_when_no_site_column(self):
        self.create_legacy_table()
        self.insert_legacy_row('legacy_1')
        self.insert_legacy_row('legacy_2')
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, stdout=StringIO())
        self.assertEqual(Notification.objects.count(), 2)
        for n in Notification.objects.all():
            self.assertEqual(n.site_id, self.site_a.pk)

    def test_preserves_explicit_site_id_and_fills_null(self):
        self.create_legacy_table(with_site_column=True)
        self.insert_legacy_row('null_site', with_site_column=True, site_id=None)
        self.insert_legacy_row('on_site_a', with_site_column=True, site_id=self.site_a.pk)
        self.insert_legacy_row('on_site_b', with_site_column=True, site_id=self.site_b.pk)
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, stdout=StringIO())
        self.assertEqual(Notification.objects.count(), 3)
        self.assertEqual(Notification.objects.get(verb='null_site').site_id, self.site_a.pk)
        self.assertEqual(Notification.objects.get(verb='on_site_a').site_id, self.site_a.pk)
        self.assertEqual(Notification.objects.get(verb='on_site_b').site_id, self.site_b.pk)

    def test_dry_run_writes_nothing(self):
        self.create_legacy_table()
        self.insert_legacy_row('only_one')
        out = StringIO()
        call_command('copy_legacy_notifications', dry_run=True, stdout=out)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertIn('DRY RUN', out.getvalue())

    def test_errors_when_default_site_required_but_missing(self):
        self.create_legacy_table()
        self.insert_legacy_row('orphan')
        with self.assertRaises(CommandError):
            call_command('copy_legacy_notifications')

    def test_errors_when_target_already_has_rows(self):
        notify.send(self.from_user, recipient=self.to_user, verb='already_here', site=self.site_a)
        self.create_legacy_table()
        self.insert_legacy_row('legacy')
        with self.assertRaises(CommandError):
            call_command('copy_legacy_notifications', default_site=self.site_a.pk)

    def test_force_copies_even_when_target_has_rows(self):
        notify.send(self.from_user, recipient=self.to_user, verb='already_here', site=self.site_a)
        before = Notification.objects.count()
        self.create_legacy_table()
        self.insert_legacy_row('legacy')
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, force=True, stdout=StringIO())
        self.assertEqual(Notification.objects.count(), before + 1)

    def test_errors_when_default_site_does_not_exist(self):
        self.create_legacy_table()
        self.insert_legacy_row('orphan')
        with self.assertRaises(CommandError):
            call_command('copy_legacy_notifications', default_site=9999)

    def test_errors_when_source_missing_required_columns(self):
        """Source schema older than expected: report the missing columns instead of a SQL error."""
        self.create_legacy_table(columns={k: v for k, v in LEGACY_COLUMNS.items() if k != 'data'})
        self.insert_legacy_row('too_old', columns=[c for c in BASE_COLS if c != 'data'])
        with self.assertRaises(CommandError) as cm:
            call_command('copy_legacy_notifications', default_site=self.site_a.pk)
        self.assertIn('data', str(cm.exception))


class CopyLegacyNotificationsDatabaseFlagTest(LegacyTableMixin, SiteTestCase):
    """The command honors --database for projects routing notifications elsewhere."""

    databases = {'default', 'aux'}

    def setUp(self):
        super().setUp()
        self.from_user_aux = User.objects.using('aux').create(username='from', password='pwd')
        self.to_user_aux = User.objects.using('aux').create(username='to', password='pwd')

    def test_database_flag_routes_to_aux(self):
        self.create_legacy_table(alias='aux')
        self.insert_legacy_row('aux_only', alias='aux', recipient=self.to_user_aux, actor=self.from_user_aux)
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, database='aux', stdout=StringIO())
        self.assertEqual(Notification.objects.using('aux').count(), 1)
        self.assertEqual(Notification.objects.using('aux').first().verb, 'aux_only')
        # default DB untouched
        self.assertEqual(Notification.objects.count(), 0)

    def test_default_alias_unchanged_when_flag_omitted(self):
        self.create_legacy_table()
        self.insert_legacy_row('default_only')
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, stdout=StringIO())
        self.assertEqual(Notification.objects.count(), 1)
        # aux DB not touched
        self.assertEqual(Notification.objects.using('aux').count(), 0)


class RecipientVariantTest(SiteTestCase):
    """notify.send fan-out paths each stamp every produced row with a site."""

    def setUp(self):
        super().setUp()
        self.to_user_2 = User.objects.create_user(username='to_2', password='pwd')

    def test_group_recipient_each_member_stamped(self):
        group = Group.objects.create(name='testers')
        group.user_set.add(self.to_user, self.to_user_2)
        notify.send(self.from_user, recipient=group, verb='group_msg', site=self.site_b)
        notifications = Notification.objects.filter(verb='group_msg')
        self.assertEqual(notifications.count(), 2)
        for n in notifications:
            self.assertEqual(n.site_id, self.site_b.pk)
        self.assertSetEqual({n.recipient_id for n in notifications}, {self.to_user.pk, self.to_user_2.pk})

    def test_list_recipient_each_stamped(self):
        notify.send(self.from_user, recipient=[self.to_user, self.to_user_2], verb='list_msg', site=self.site_b)
        notifications = Notification.objects.filter(verb='list_msg')
        self.assertEqual(notifications.count(), 2)
        for n in notifications:
            self.assertEqual(n.site_id, self.site_b.pk)

    def test_queryset_recipient_each_stamped(self):
        qs = User.objects.filter(username__startswith='to')
        notify.send(self.from_user, recipient=qs, verb='qs_msg', site=self.site_a)
        notifications = Notification.objects.filter(verb='qs_msg')
        self.assertEqual(notifications.count(), 2)
        for n in notifications:
            self.assertEqual(n.site_id, self.site_a.pk)

    def test_single_recipient_produces_exactly_one_row(self):
        """Confirms the base signal handler isn't still attached alongside ours."""
        notify.send(self.from_user, recipient=self.to_user, verb='solo')
        self.assertEqual(Notification.objects.filter(verb='solo').count(), 1)


class InheritedManagerTest(SiteTestCase):
    """Manager methods defined on AbstractNotification still work on the swapped model."""

    def setUp(self):
        super().setUp()
        for i in range(3):
            notify.send(self.from_user, recipient=self.to_user, verb=f'm{i}', site=self.site_a)
        notify.send(self.from_user, recipient=self.to_user, verb='m_b', site=self.site_b)

    def test_unread_manager(self):
        self.assertEqual(Notification.objects.unread().count(), 4)
        n = Notification.objects.first()
        n.mark_as_read()
        self.assertEqual(Notification.objects.unread().count(), 3)

    def test_read_manager(self):
        n = Notification.objects.filter(verb='m0').first()
        n.mark_as_read()
        self.assertEqual(Notification.objects.read().count(), 1)
        self.assertEqual(Notification.objects.read().first().verb, 'm0')

    def test_mark_all_as_read_at_manager_level(self):
        Notification.objects.mark_all_as_read()
        self.assertEqual(Notification.objects.unread().count(), 0)

    def test_on_site_manager_returns_current_site_only(self):
        with override_settings(SITE_ID=self.site_a.pk):
            Site.objects.clear_cache()
            self.assertEqual(Notification.on_site.count(), 3)
            self.assertSetEqual({n.verb for n in Notification.on_site.all()}, {'m0', 'm1', 'm2'})
        with override_settings(SITE_ID=self.site_b.pk):
            Site.objects.clear_cache()
            self.assertEqual(Notification.on_site.count(), 1)
            self.assertEqual(Notification.on_site.first().verb, 'm_b')

    def test_on_site_chains_with_queryset_methods(self):
        """on_site.unread() returns NotificationQuerySet methods on top of CurrentSiteManager."""
        with override_settings(SITE_ID=self.site_a.pk):
            Site.objects.clear_cache()
            self.assertEqual(Notification.on_site.unread().count(), 3)


class TemplateTagDirectTest(SiteTestCase):
    """Template tag callables work outside of a request context."""

    def test_has_notification_filter_with_unread_rows(self):
        notify.send(self.from_user, recipient=self.to_user, verb='hi', site=self.site_a)
        self.assertTrue(has_notification(self.to_user))

    def test_has_notification_filter_with_no_rows(self):
        self.assertFalse(has_notification(self.to_user))

    def test_has_notification_filter_with_anonymous_user(self):
        self.assertFalse(has_notification(None))

    def test_unread_count_cache_key_uses_current_site(self):
        self.assertIn(f'site_{self.site_a.pk}', unread_count_cache_key(self.to_user))


class AnonymousAccessTest(TestCase):
    """Anonymous users get sensible empty responses from the live endpoints."""

    def test_live_unread_count_anonymous(self):
        response = self.client.get(reverse('notifications:live_unread_notification_count'))
        self.assertEqual(response.json(), {'unread_count': 0})

    def test_live_all_count_anonymous(self):
        response = self.client.get(reverse('notifications:live_all_notification_count'))
        self.assertEqual(response.json(), {'all_count': 0})

    def test_live_unread_list_anonymous(self):
        response = self.client.get(reverse('notifications:live_unread_notification_list'))
        self.assertEqual(response.json(), {'unread_count': 0, 'unread_list': []})

    def test_live_all_list_anonymous(self):
        response = self.client.get(reverse('notifications:live_all_notification_list'))
        self.assertEqual(response.json(), {'all_count': 0, 'all_list': []})

    def test_list_view_anonymous_redirects(self):
        response = self.client.get(reverse('notifications:all'))
        self.assertEqual(response.status_code, 302)


class SoftDeleteSitesInteractionTest(SiteTestCase):
    """SOFT_DELETE config still works alongside site scoping."""

    def setUp(self):
        super().setUp()
        notify.send(self.from_user, recipient=self.to_user, verb='soft_a', site=self.site_a)
        notify.send(self.from_user, recipient=self.to_user, verb='soft_b', site=self.site_b)
        self.client.force_login(self.to_user)

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'SOFT_DELETE': True, 'USE_JSONFIELD': True})
    def test_soft_delete_blocks_cross_site_request(self):
        n_b = Notification.objects.get(verb='soft_b')
        response = self.client.post(reverse('notifications:delete', kwargs={'slug': n_b.slug}))
        self.assertEqual(response.status_code, 404)
        n_b.refresh_from_db()
        self.assertFalse(n_b.deleted)

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'SOFT_DELETE': True, 'USE_JSONFIELD': True})
    def test_soft_delete_succeeds_on_same_site(self):
        n_a = Notification.objects.get(verb='soft_a')
        response = self.client.post(reverse('notifications:delete', kwargs={'slug': n_a.slug}))
        self.assertEqual(response.status_code, 302)
        n_a.refresh_from_db()
        self.assertTrue(n_a.deleted)
        # Row is not removed
        self.assertTrue(Notification.objects.filter(pk=n_a.pk).exists())

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'SOFT_DELETE': True, 'USE_JSONFIELD': True})
    def test_all_view_excludes_soft_deleted_on_current_site(self):
        n_a = Notification.objects.get(verb='soft_a')
        n_a.deleted = True
        n_a.save(update_fields=['deleted'])
        response = self.client.get(reverse('notifications:all'))
        self.assertEqual(list(response.context['notifications']), [])


class MigrationStateTest(TestCase):
    """Model state and migrations agree, so downstream makemigrations --check stays clean."""

    def test_no_pending_migrations(self):
        try:
            call_command('makemigrations', 'notifications_sites', check=True, dry_run=True, stdout=StringIO())
        except SystemExit:
            self.fail('notifications_sites has model changes without a migration')
