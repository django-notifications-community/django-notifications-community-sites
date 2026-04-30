"""Tests for notifications_sites."""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from notifications.signals import notify
from notifications.swappable import load_notification_model

Notification = load_notification_model()


class NotifyHandlerSiteStampingTest(TestCase):
    """The site-aware notify_handler stamps each notification with a site."""

    def setUp(self):
        Site.objects.clear_cache()
        self.from_user = User.objects.create_user(username='from', password='pwd')
        self.to_user = User.objects.create_user(username='to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')

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

    def test_site_id_kwarg_is_rejected(self):
        """Passing site_id= is a typo for site=; reject loudly so it doesn't land in data."""
        with self.assertRaises(TypeError):
            notify.send(self.from_user, recipient=self.to_user, verb='pinged', site_id=self.site_b.pk)


class ViewFilteringTest(TestCase):
    """Base views filter by the current site via the registered hook."""

    def setUp(self):
        Site.objects.clear_cache()
        cache.clear()
        self.from_user = User.objects.create_user(username='from', password='pwd')
        self.to_user = User.objects.create_user(username='to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')
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


class CacheKeyNamespacingTest(TestCase):
    """Each site has its own unread-count cache key."""

    def setUp(self):
        Site.objects.clear_cache()
        cache.clear()
        self.from_user = User.objects.create_user(username='from', password='pwd')
        self.to_user = User.objects.create_user(username='to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')

    def test_cache_key_includes_site_pk(self):
        from notifications.templatetags.notifications_tags import unread_count_cache_key

        self.assertEqual(
            unread_count_cache_key(self.to_user),
            f'notifications_unread_count_{self.to_user.pk}_site_{self.site_a.pk}',
        )

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'CACHE_TIMEOUT': 60, 'USE_JSONFIELD': True})
    def test_concurrent_site_caches_do_not_collide(self):
        from notifications.templatetags.notifications_tags import get_cached_notification_unread_count

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
        key_a = f'notifications_unread_count_{self.to_user.pk}_site_{self.site_a.pk}'
        key_b = f'notifications_unread_count_{self.to_user.pk}_site_{self.site_b.pk}'
        self.assertEqual(cache.get(key_a), 1)
        self.assertEqual(cache.get(key_b), 1)

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'CACHE_TIMEOUT': 60, 'USE_JSONFIELD': True})
    def test_mark_as_read_invalidates_current_site_cache(self):
        notify.send(self.from_user, recipient=self.to_user, verb='a', site=self.site_a)
        from notifications.templatetags.notifications_tags import get_cached_notification_unread_count

        get_cached_notification_unread_count(self.to_user)
        key_a = f'notifications_unread_count_{self.to_user.pk}_site_{self.site_a.pk}'
        self.assertEqual(cache.get(key_a), 1)

        n = Notification.objects.first()
        self.client.force_login(self.to_user)
        self.client.post(reverse('notifications:mark_as_read', kwargs={'slug': n.slug}))
        self.assertIsNone(cache.get(key_a))


class AdminTest(TestCase):
    """The companion admin includes the site column."""

    def test_list_display_includes_site(self):
        from notifications_sites.admin import NotificationAdmin

        adm = NotificationAdmin(Notification, None)
        self.assertIn('site', adm.get_list_display(None))

    def test_list_filter_includes_site(self):
        from notifications_sites.admin import NotificationAdmin

        adm = NotificationAdmin(Notification, None)
        self.assertIn('site', adm.get_list_filter(None))


class SystemCheckTest(TestCase):
    """System checks fire on misconfiguration and pass when configured correctly."""

    def test_sites_installed_passes(self):
        from notifications_sites.checks import check_sites_installed

        self.assertEqual(check_sites_installed(None), [])

    @override_settings(INSTALLED_APPS=[a for a in settings.INSTALLED_APPS if a != 'django.contrib.sites'])
    def test_sites_installed_errors(self):
        from notifications_sites.checks import check_sites_installed

        errors = check_sites_installed(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E001')

    def test_site_id_passes(self):
        from notifications_sites.checks import check_site_id

        self.assertEqual(check_site_id(None), [])

    @override_settings(SITE_ID=None)
    def test_site_id_errors_when_unset(self):
        from notifications_sites.checks import check_site_id

        errors = check_site_id(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E002')

    def test_notification_model_setting_passes(self):
        from notifications_sites.checks import check_notification_model_setting

        self.assertEqual(check_notification_model_setting(None), [])

    @override_settings(NOTIFICATIONS_NOTIFICATION_MODEL='myapp.MyNotification')
    def test_notification_model_setting_errors_on_mismatch(self):
        from notifications_sites.checks import check_notification_model_setting

        errors = check_notification_model_setting(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E003')

    def test_app_ordering_passes(self):
        from notifications_sites.checks import check_app_ordering

        self.assertEqual(check_app_ordering(None), [])

    def test_app_ordering_errors_when_misordered(self):
        from notifications_sites.checks import check_app_ordering

        fake_configs = {
            'admin': None,
            'notifications_sites': None,
            'notifications': None,
        }
        with patch('notifications_sites.checks.apps.app_configs', fake_configs):
            errors = check_app_ordering(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'notifications_sites.E004')


class CopyLegacyNotificationsCommandTest(TestCase):
    """Opt-in management command to migrate legacy notifications_notification rows."""

    BASE_COLS_SQL = """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level VARCHAR(20) NOT NULL DEFAULT 'info',
        recipient_id INTEGER NOT NULL,
        unread BOOLEAN NOT NULL DEFAULT 1,
        actor_content_type_id INTEGER NOT NULL,
        actor_object_id VARCHAR(255) NOT NULL,
        verb VARCHAR(255) NOT NULL,
        description TEXT,
        target_content_type_id INTEGER,
        target_object_id VARCHAR(255),
        action_object_content_type_id INTEGER,
        action_object_object_id VARCHAR(255),
        timestamp DATETIME NOT NULL,
        public BOOLEAN NOT NULL DEFAULT 1,
        deleted BOOLEAN NOT NULL DEFAULT 0,
        emailed BOOLEAN NOT NULL DEFAULT 0,
        data TEXT
    """

    def setUp(self):
        Site.objects.clear_cache()
        self.from_user = User.objects.create_user(username='legacy_from', password='pwd')
        self.to_user = User.objects.create_user(username='legacy_to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')

    def _create_legacy_table(self, with_site_column=False):
        cols_sql = self.BASE_COLS_SQL
        if with_site_column:
            cols_sql += ', site_id INTEGER'
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS notifications_notification')
            cursor.execute(f'CREATE TABLE notifications_notification ({cols_sql})')
        self.addCleanup(self._drop_legacy_table)

    def _drop_legacy_table(self):
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS notifications_notification')

    def _insert_legacy_row(self, verb, site_id=None, with_site_column=True):
        ct = ContentType.objects.get_for_model(self.from_user)
        cols = [
            'level',
            'recipient_id',
            'unread',
            'actor_content_type_id',
            'actor_object_id',
            'verb',
            'description',
            'target_content_type_id',
            'target_object_id',
            'action_object_content_type_id',
            'action_object_object_id',
            'timestamp',
            'public',
            'deleted',
            'emailed',
            'data',
        ]
        values = [
            'info',
            self.to_user.pk,
            True,
            ct.pk,
            str(self.from_user.pk),
            verb,
            None,
            None,
            None,
            None,
            None,
            timezone.now(),
            True,
            False,
            False,
            None,
        ]
        if with_site_column:
            cols.append('site_id')
            values.append(site_id)
        placeholders = ', '.join(['%s'] * len(cols))
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO notifications_notification ({", ".join(cols)}) VALUES ({placeholders})',
                values,
            )

    def test_noop_when_source_table_missing(self):
        out = StringIO()
        call_command('copy_legacy_notifications', stdout=out)
        self.assertIn('nothing to copy', out.getvalue().lower())
        self.assertEqual(load_notification_model().objects.count(), 0)

    def test_noop_when_source_empty(self):
        self._create_legacy_table(with_site_column=False)
        out = StringIO()
        call_command('copy_legacy_notifications', stdout=out)
        self.assertEqual(load_notification_model().objects.count(), 0)
        self.assertIn('nothing to copy', out.getvalue().lower())

    def test_copies_rows_with_default_site_when_no_site_column(self):
        self._create_legacy_table(with_site_column=False)
        self._insert_legacy_row('legacy_1', with_site_column=False)
        self._insert_legacy_row('legacy_2', with_site_column=False)
        out = StringIO()
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, stdout=out)
        N = load_notification_model()
        self.assertEqual(N.objects.count(), 2)
        for n in N.objects.all():
            self.assertEqual(n.site_id, self.site_a.pk)

    def test_preserves_explicit_site_id_and_fills_null(self):
        self._create_legacy_table(with_site_column=True)
        self._insert_legacy_row('null_site', site_id=None)
        self._insert_legacy_row('on_site_a', site_id=self.site_a.pk)
        self._insert_legacy_row('on_site_b', site_id=self.site_b.pk)
        out = StringIO()
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, stdout=out)
        N = load_notification_model()
        self.assertEqual(N.objects.count(), 3)
        self.assertEqual(N.objects.get(verb='null_site').site_id, self.site_a.pk)
        self.assertEqual(N.objects.get(verb='on_site_a').site_id, self.site_a.pk)
        self.assertEqual(N.objects.get(verb='on_site_b').site_id, self.site_b.pk)

    def test_dry_run_writes_nothing(self):
        self._create_legacy_table(with_site_column=False)
        self._insert_legacy_row('only_one', with_site_column=False)
        out = StringIO()
        call_command('copy_legacy_notifications', dry_run=True, stdout=out)
        self.assertEqual(load_notification_model().objects.count(), 0)
        self.assertIn('DRY RUN', out.getvalue())

    def test_errors_when_default_site_required_but_missing(self):
        self._create_legacy_table(with_site_column=False)
        self._insert_legacy_row('orphan', with_site_column=False)
        with self.assertRaises(CommandError):
            call_command('copy_legacy_notifications')

    def test_errors_when_target_already_has_rows(self):
        notify.send(self.from_user, recipient=self.to_user, verb='already_here', site=self.site_a)
        self._create_legacy_table(with_site_column=False)
        self._insert_legacy_row('legacy', with_site_column=False)
        with self.assertRaises(CommandError):
            call_command('copy_legacy_notifications', default_site=self.site_a.pk)

    def test_force_copies_even_when_target_has_rows(self):
        notify.send(self.from_user, recipient=self.to_user, verb='already_here', site=self.site_a)
        N = load_notification_model()
        before = N.objects.count()
        self._create_legacy_table(with_site_column=False)
        self._insert_legacy_row('legacy', with_site_column=False)
        out = StringIO()
        call_command('copy_legacy_notifications', default_site=self.site_a.pk, force=True, stdout=out)
        self.assertEqual(N.objects.count(), before + 1)

    def test_errors_when_default_site_does_not_exist(self):
        self._create_legacy_table(with_site_column=False)
        self._insert_legacy_row('orphan', with_site_column=False)
        with self.assertRaises(CommandError):
            call_command('copy_legacy_notifications', default_site=9999)


class DataKwargTest(TestCase):
    """notify.send(..., data={...}) survives the handler's data merging."""

    def setUp(self):
        Site.objects.clear_cache()
        self.from_user = User.objects.create_user(username='dk_from', password='pwd')
        self.to_user = User.objects.create_user(username='dk_to', password='pwd')
        self.site_a = Site.objects.get(pk=1)

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'USE_JSONFIELD': True})
    def test_explicit_data_kwarg_is_preserved(self):
        notify.send(self.from_user, recipient=self.to_user, verb='dk1', data={'foo': 'bar'})
        n = Notification.objects.get(verb='dk1')
        self.assertEqual(n.data, {'foo': 'bar'})

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'USE_JSONFIELD': True})
    def test_explicit_data_merges_with_extras(self):
        notify.send(
            self.from_user, recipient=self.to_user, verb='dk2', data={'foo': 'bar'}, extra='zzz'
        )
        n = Notification.objects.get(verb='dk2')
        self.assertEqual(n.data, {'foo': 'bar', 'extra': 'zzz'})

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'USE_JSONFIELD': True})
    def test_no_data_no_extras_leaves_data_null(self):
        notify.send(self.from_user, recipient=self.to_user, verb='dk3')
        n = Notification.objects.get(verb='dk3')
        self.assertIsNone(n.data)

    @override_settings(DJANGO_NOTIFICATIONS_CONFIG={'USE_JSONFIELD': True})
    def test_caller_dict_not_mutated(self):
        payload = {'foo': 'bar'}
        notify.send(
            self.from_user, recipient=self.to_user, verb='dk4', data=payload, extra='zzz'
        )
        self.assertEqual(payload, {'foo': 'bar'})


class RecipientVariantTest(TestCase):
    """notify.send fan-out paths each stamp every produced row with a site."""

    def setUp(self):
        Site.objects.clear_cache()
        self.from_user = User.objects.create_user(username='rv_from', password='pwd')
        self.to_user_1 = User.objects.create_user(username='rv_to_1', password='pwd')
        self.to_user_2 = User.objects.create_user(username='rv_to_2', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')

    def test_group_recipient_each_member_stamped(self):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name='testers')
        group.user_set.add(self.to_user_1, self.to_user_2)
        notify.send(self.from_user, recipient=group, verb='group_msg', site=self.site_b)
        notifications = Notification.objects.filter(verb='group_msg')
        self.assertEqual(notifications.count(), 2)
        for n in notifications:
            self.assertEqual(n.site_id, self.site_b.pk)
        self.assertSetEqual(
            {n.recipient_id for n in notifications},
            {self.to_user_1.pk, self.to_user_2.pk},
        )

    def test_list_recipient_each_stamped(self):
        notify.send(
            self.from_user,
            recipient=[self.to_user_1, self.to_user_2],
            verb='list_msg',
            site=self.site_b,
        )
        notifications = Notification.objects.filter(verb='list_msg')
        self.assertEqual(notifications.count(), 2)
        for n in notifications:
            self.assertEqual(n.site_id, self.site_b.pk)

    def test_queryset_recipient_each_stamped(self):
        qs = User.objects.filter(username__startswith='rv_to_')
        notify.send(self.from_user, recipient=qs, verb='qs_msg', site=self.site_a)
        notifications = Notification.objects.filter(verb='qs_msg')
        self.assertEqual(notifications.count(), 2)
        for n in notifications:
            self.assertEqual(n.site_id, self.site_a.pk)

    def test_single_recipient_produces_exactly_one_row(self):
        """Confirms the base signal handler isn't still attached alongside ours."""
        notify.send(self.from_user, recipient=self.to_user_1, verb='solo')
        self.assertEqual(Notification.objects.filter(verb='solo').count(), 1)


class InheritedManagerTest(TestCase):
    """Manager methods defined on AbstractNotification still work on the swapped model."""

    def setUp(self):
        Site.objects.clear_cache()
        self.from_user = User.objects.create_user(username='im_from', password='pwd')
        self.to_user = User.objects.create_user(username='im_to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')
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
            self.assertSetEqual(
                {n.verb for n in Notification.on_site.all()},
                {'m0', 'm1', 'm2'},
            )
        with override_settings(SITE_ID=self.site_b.pk):
            Site.objects.clear_cache()
            self.assertEqual(Notification.on_site.count(), 1)
            self.assertEqual(Notification.on_site.first().verb, 'm_b')

    def test_on_site_chains_with_queryset_methods(self):
        """on_site.unread() returns NotificationQuerySet methods on top of CurrentSiteManager."""
        with override_settings(SITE_ID=self.site_a.pk):
            Site.objects.clear_cache()
            self.assertEqual(Notification.on_site.unread().count(), 3)


class TemplateTagDirectTest(TestCase):
    """Template tag callables work outside of a request context."""

    def setUp(self):
        Site.objects.clear_cache()
        cache.clear()
        self.from_user = User.objects.create_user(username='tt_from', password='pwd')
        self.to_user = User.objects.create_user(username='tt_to', password='pwd')
        self.site_a = Site.objects.get(pk=1)

    def test_has_notification_filter_with_unread_rows(self):
        from notifications.templatetags.notifications_tags import has_notification

        notify.send(self.from_user, recipient=self.to_user, verb='hi', site=self.site_a)
        self.assertTrue(has_notification(self.to_user))

    def test_has_notification_filter_with_no_rows(self):
        from notifications.templatetags.notifications_tags import has_notification

        self.assertFalse(has_notification(self.to_user))

    def test_has_notification_filter_with_anonymous_user(self):
        from notifications.templatetags.notifications_tags import has_notification

        self.assertFalse(has_notification(None))

    def test_unread_count_cache_key_uses_current_site(self):
        from notifications.templatetags.notifications_tags import unread_count_cache_key

        key = unread_count_cache_key(self.to_user)
        self.assertIn(f'site_{self.site_a.pk}', key)


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


class SoftDeleteSitesInteractionTest(TestCase):
    """SOFT_DELETE config still works alongside site scoping."""

    def setUp(self):
        Site.objects.clear_cache()
        cache.clear()
        self.from_user = User.objects.create_user(username='sd_from', password='pwd')
        self.to_user = User.objects.create_user(username='sd_to', password='pwd')
        self.site_a = Site.objects.get(pk=1)
        self.site_b = Site.objects.create(domain='b.example.com', name='Site B')
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
