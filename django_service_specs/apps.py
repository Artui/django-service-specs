"""The app a project may list for this package, which adds nothing by being listed."""

from __future__ import annotations

from django.apps import AppConfig


class DjangoServiceSpecsConfig(AppConfig):
    """The package's app, kept so a project listing it keeps starting.

    Optional, and listing it does nothing: the package works unlisted, owns no
    models, so it sets no ``default_auto_field``, and registers no system
    check. The report of open specs a management command serves belongs to
    that command, and django-spec-cli registers it when ``"django_spec_cli"``
    is listed. A project listing ``"django_service_specs"`` or this config
    from before it moved starts unchanged
    (test_a_project_listing_the_app_starts_and_its_check_reports_nothing).
    """

    name = "django_service_specs"
