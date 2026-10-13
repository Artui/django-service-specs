"""Fixtures for the mutation tests."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def media(settings: Any) -> Iterator[str]:
    """Default storage in a directory removed after the test, so no upload outlives it."""
    with tempfile.TemporaryDirectory() as root:
        settings.MEDIA_ROOT = root
        yield root
