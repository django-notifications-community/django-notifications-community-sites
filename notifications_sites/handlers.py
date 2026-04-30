"""Site-aware replacement for ``notifications.base.models.notify_handler``.

Stamps ``Site.objects.get_current()`` (or the explicit ``site=`` kwarg)
on each notification. Otherwise mirrors the base handler verbatim. The
companion's ``apps.ready()`` disconnects the base handler and connects
this one in its place.
"""

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.db.models.query import QuerySet
from django.utils import timezone
from notifications.settings import get_config
from notifications.swappable import load_notification_model


def site_aware_notify_handler(verb, **kwargs):
    """Create Notification rows on the ``notify`` signal, stamping the current site."""
    kwargs.pop('signal', None)
    recipient = kwargs.pop('recipient')
    actor = kwargs.pop('sender')
    optional_objs = [(kwargs.pop(opt, None), opt) for opt in ('target', 'action_object')]

    site = kwargs.pop('site', None)
    if site is None:
        site = Site.objects.get_current()

    public = bool(kwargs.pop('public', True))
    description = kwargs.pop('description', None)
    timestamp = kwargs.pop('timestamp', timezone.now())
    Notification = load_notification_model()
    level = kwargs.pop('level', Notification.LEVELS.info)
    actor_for_concrete_model = kwargs.pop('actor_for_concrete_model', True)

    if isinstance(recipient, Group):
        recipients = recipient.user_set.all()
    elif isinstance(recipient, QuerySet | list):
        recipients = recipient
    else:
        recipients = [recipient]

    new_notifications = []

    for recipient in recipients:
        newnotify = Notification(
            recipient=recipient,
            actor_content_type=ContentType.objects.get_for_model(actor, for_concrete_model=actor_for_concrete_model),
            actor_object_id=actor.pk,
            verb=str(verb),
            public=public,
            description=description,
            timestamp=timestamp,
            level=level,
            site=site,
        )

        for obj, opt in optional_objs:
            if obj is not None:
                for_concrete_model = kwargs.get(f'{opt}_for_concrete_model', True)
                setattr(newnotify, f'{opt}_object_id', obj.pk)
                setattr(
                    newnotify,
                    f'{opt}_content_type',
                    ContentType.objects.get_for_model(obj, for_concrete_model=for_concrete_model),
                )

        if kwargs and get_config()['USE_JSONFIELD']:
            data_kwargs = {}
            for key in list(kwargs.keys()):
                if key.endswith('_for_concrete_model'):
                    continue
                if hasattr(newnotify, key):
                    setattr(newnotify, key, kwargs[key])
                else:
                    data_kwargs[key] = kwargs[key]
            newnotify.data = data_kwargs

        new_notifications.append(newnotify)

    Notification.objects.bulk_create(new_notifications)

    return new_notifications
