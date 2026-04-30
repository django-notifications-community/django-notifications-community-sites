"""Copy rows from notifications_notification into notifications_sites_notification.

The companion does not auto-migrate legacy rows during ``migrate``: there
is no correct default for which Site a row should belong to, so silently
picking ``SITE_ID`` would be wrong for any multi-site setup. This command
is the opt-in upgrade path.
"""

from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from notifications.swappable import load_notification_model

SOURCE_TABLE = 'notifications_notification'

BASE_COLS = (
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
)


class Command(BaseCommand):
    help = (
        'Copy rows from notifications_notification into the swapped '
        'Notification table, assigning a Site to any row whose '
        'site_id is NULL or absent.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--default-site',
            type=int,
            help=(
                'Site PK to assign to rows with NULL site_id, or to every '
                'row when the source has no site_id column. Required '
                'unless --dry-run.'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be copied without writing anything.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Copy even if the target table already has rows. Off by default to avoid creating duplicates.',
        )
        parser.add_argument(
            '--database',
            default=DEFAULT_DB_ALIAS,
            help=(
                'Database alias to copy from and to. Defaults to "default". '
                'Use this when DATABASE_ROUTERS routes notifications to a '
                'non-default alias.'
            ),
        )

    def handle(self, *args, **options):
        default_site = options['default_site']
        dry_run = options['dry_run']
        force = options['force']
        database = options['database']

        connection = connections[database]
        target_table = load_notification_model()._meta.db_table

        introspection = connection.introspection
        cursor = connection.cursor()

        if SOURCE_TABLE not in introspection.table_names():
            self.stdout.write(f'No {SOURCE_TABLE} table found — nothing to copy.')
            return

        if target_table == SOURCE_TABLE:
            raise CommandError(
                f'Target table resolves to {target_table}, the same as the source. '
                'Confirm NOTIFICATIONS_NOTIFICATION_MODEL points at the companion model.'
            )

        source_columns = {col.name for col in introspection.get_table_description(cursor, SOURCE_TABLE)}
        missing = sorted(set(BASE_COLS) - source_columns)
        if missing:
            raise CommandError(
                f'{SOURCE_TABLE} is missing expected columns: {", ".join(missing)}. '
                'The source schema is older or different from what the standard '
                'django-notifications-community migration produces. Either back-fill '
                'the columns first or copy data with a custom SQL script.'
            )
        has_site_column = 'site_id' in source_columns

        cursor.execute(f'SELECT COUNT(*) FROM {SOURCE_TABLE}')
        source_count = cursor.fetchone()[0]
        cursor.execute(f'SELECT COUNT(*) FROM {target_table}')
        target_count = cursor.fetchone()[0]

        if has_site_column:
            cursor.execute(f'SELECT COUNT(*) FROM {SOURCE_TABLE} WHERE site_id IS NULL')
            null_site_count = cursor.fetchone()[0]
        else:
            null_site_count = source_count

        self.stdout.write(f'Source ({SOURCE_TABLE}): {source_count} row(s)')
        if has_site_column:
            self.stdout.write(f'  with NULL site_id: {null_site_count}')
        else:
            self.stdout.write('  (no site_id column; every row needs a default)')
        self.stdout.write(f'Target ({target_table}): {target_count} row(s)')

        if source_count == 0:
            self.stdout.write('Nothing to copy.')
            return

        if target_count > 0 and not force:
            raise CommandError(
                f'{target_table} already contains {target_count} row(s). '
                'Re-run with --force to copy anyway (this can create duplicates).'
            )

        if null_site_count > 0 and default_site is None and not dry_run:
            raise CommandError(f'{null_site_count} row(s) need a default Site. Pass --default-site=<pk>.')

        if default_site is not None and not Site.objects.using(database).filter(pk=default_site).exists():
            raise CommandError(f'Site with pk={default_site} does not exist.')

        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN: would copy {source_count} row(s).'))
            return

        select_cols = ', '.join(BASE_COLS)
        if has_site_column:
            select_cols += ', COALESCE(site_id, %s)'
        else:
            select_cols += ', %s'
        sql = f'INSERT INTO {target_table} ({", ".join(BASE_COLS)}, site_id) SELECT {select_cols} FROM {SOURCE_TABLE}'

        with transaction.atomic(using=database):
            cursor.execute(sql, [default_site])
            copied = cursor.rowcount

        self.stdout.write(self.style.SUCCESS(f'Copied {copied} row(s).'))
