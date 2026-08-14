"""Backward-compatible Django development launcher."""

import os
import sys

from django.core.management import execute_from_command_line


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    execute_from_command_line([sys.argv[0], "runserver", "127.0.0.1:8000", *sys.argv[1:]])


if __name__ == "__main__":
    main()
