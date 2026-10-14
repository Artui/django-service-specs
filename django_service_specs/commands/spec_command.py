"""``SpecCommand`` - a registry of specs as one management command."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from django_service_specs.registry.spec_registry import SpecRegistry


class SpecCommand(BaseCommand):
    """A management command serving every spec in a registry, one subcommand each.

    Declared by subclassing, in the project's own ``management/commands/``
    module, which names the registry::

        class Command(SpecCommand):
            registry = notes_registry

    The registry is the subclass's to name, so one project can expose two
    registries under two command names.
    """

    registry: SpecRegistry
