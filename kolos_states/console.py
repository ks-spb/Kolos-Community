"""Explicit UTF-8 for standalone CLI pipes, independent of Windows code page.

Imported without side effects. Library users keep their streams unchanged;
only CLI entry points call configure_console().
"""
import sys


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        configure = getattr(stream, 'reconfigure', None)
        if configure is not None:
            configure(encoding='utf-8', errors='backslashreplace')
