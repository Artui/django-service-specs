"""The version is a single source of truth."""

from __future__ import annotations

import re

import django_service_specs
from django_service_specs.version import __version__

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_a_release_number() -> None:
    assert SEMVER.match(__version__), __version__


def test_the_package_root_re_exports_the_same_object() -> None:
    # version.py is the single source of truth and __init__.py re-exports it.
    # Two copies of the string would pass an equality check while drifting on
    # the next bump, so this asserts identity rather than equality.
    assert django_service_specs.__version__ is __version__
