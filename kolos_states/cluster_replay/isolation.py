"""Deny network connections in the replay host; text inference is a fresh process."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch


def _deny(*args: object, **kwargs: object) -> None:
    """The replay host cannot reach XWAY, WB, MCP servers or any other network service."""
    raise PermissionError('Offline replay host: network forbidden')


@contextmanager
def offline_host() -> Iterator[None]:
    """Only subprocess text inference may use networking; controllers stay offline."""
    with patch('socket.create_connection', _deny), patch('socket.socket.connect', _deny), \
         patch('socket.socket.connect_ex', _deny):
        yield
