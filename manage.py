#!/usr/bin/env python3
import os
import sys


def main():
    """Entry point for Django's management utility."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django ist nicht installiert oder in Ihrer PYTHONPATH-Umgebung nicht verfügbar."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

