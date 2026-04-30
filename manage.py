#!/usr/bin/env python
"""Manage script for the notifications_sites test project."""

import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'notifications_sites.tests.settings')
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
