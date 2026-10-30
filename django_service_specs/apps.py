"""The app a project lists for this package's translations to load."""

from __future__ import annotations

from django.apps import AppConfig


class DjangoServiceSpecsConfig(AppConfig):
    """The package's app, listed for its translation catalog to load.

    Django reads a catalog only from an installed app's ``locale`` directory or
    from ``LOCALE_PATHS``, so a language compiled beside the package's source
    catalog loads once the app is listed
    (test_listing_the_app_loads_a_catalog_beside_the_package). That is all
    listing it does: the package runs unlisted, owns no models, so it sets no
    ``default_auto_field``, and registers no system check. The report of open
    specs a management command serves belongs to that command, and
    django-spec-cli registers it when ``"django_spec_cli"`` is listed. A
    project listing ``"django_service_specs"`` or this config from before it
    moved starts unchanged
    (test_a_project_listing_the_app_starts_and_its_check_reports_nothing).
    """

    name = "django_service_specs"
