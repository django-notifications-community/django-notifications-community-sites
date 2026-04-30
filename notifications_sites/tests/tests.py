"""Tests for notifications_sites."""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
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
