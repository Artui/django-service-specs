from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest
from django.apps import AppConfig, apps

import django_service_specs.apps
from django_service_specs.apps import DjangoServiceSpecsConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_apps_py_declares_exactly_one_app_config() -> None:
    # Django picks the config itself only when the module holds exactly one
    # subclass; a second would leave the plain ``AppConfig`` in charge, so a
    # project listing the label would get a config other than the one it names.
    declared = [
        value
        for value in vars(django_service_specs.apps).values()
        if inspect.isclass(value) and issubclass(value, AppConfig) and value is not AppConfig
    ]
    assert declared == [DjangoServiceSpecsConfig]
    assert type(apps.get_app_config("django_service_specs")) is DjangoServiceSpecsConfig


def test_the_app_is_named_for_the_package_and_owns_no_models() -> None:
    config = apps.get_app_config("django_service_specs")
    assert (config.name, config.label) == ("django_service_specs", "django_service_specs")
    assert "default_auto_field" not in vars(DjangoServiceSpecsConfig)
    assert list(config.get_models()) == []


@pytest.mark.parametrize(
    "listed",
    ["django_service_specs", "django_service_specs.apps.DjangoServiceSpecsConfig"],
    ids=["label", "config"],
)
def test_a_project_listing_the_app_starts_and_its_check_reports_nothing(listed: str) -> None:
    # The app registers no system check: the unguarded-spec report belongs to
    # the management command, which django-spec-cli serves, and listing this
    # app, either way, is kept working so a project upgrading has nothing to
    # unlist. A fresh interpreter, because this one's check registry holds
    # whatever the test settings' apps registered.
    probe = f"""
import json
import django
from django.conf import settings
settings.configure(
    INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth", {listed!r}],
    DATABASES={{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}}},
)
django.setup()
from django.core.checks import run_checks
from django.core.checks.registry import registry
print(json.dumps([
    sorted(c.__module__ for c in registry.get_checks() if c.__module__.startswith("django_service_specs")),
    [m.id for m in run_checks()],
]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr
    registered, reported = json.loads(completed.stdout)
    assert registered == []
    assert reported == []


def test_importing_the_app_before_setup_loads_no_model() -> None:
    # ``apps.py`` is imported while the app registry is still being populated,
    # so nothing it imports, the package root included, may reach a model or
    # ``get_user_model``. A fresh interpreter, because this one is set up.
    probe = """
import json, sys
from django.conf import settings
settings.configure(INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth"])
from django.apps import apps
import django_service_specs.apps
print(json.dumps([apps.ready, sorted(m for m in sys.modules if m.endswith(".models"))]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr
    ready, models = json.loads(completed.stdout)
    assert ready is False
    assert [m for m in models if m.startswith("django.contrib.")] == []
