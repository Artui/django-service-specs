from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.types.affordance import Affordance
from django_service_specs.types.affordance_declarer import AffordanceDeclarer


@dataclass(frozen=True)
class SpecLink(AffordanceDeclarer):
    """A ``SelectorSpec.affordances`` value naming which row field fills which read of its target.

    A bare ``ServiceSpec`` in the mapping means ``SpecLink(spec)``: its reads
    bind by inference. A read binds to the field ``arguments`` names, else to
    the output field of the same name, else, when one required read is left
    and the output marks one field ``HANDLE``, to that field (``id`` to
    ``pk``). Optional reads bind only by name or by ``arguments``.

    ``affordances`` is the target's, so the answers, their annotations and
    the schema are those of the bare spec. The inference reads the rows'
    output, which a presenter may only answer once the apps are loaded, so it
    is checked against a built registry by
    [`check_links`][django_service_specs.links.check_links.check_links],
    never here.

    Attributes:
        spec: The operation the link leads to, a ``ServiceSpec``.
        arguments: ``{read: output field}``, binding a read explicitly.

    Raises:
        ImproperlyConfigured: ``spec`` is not a ``ServiceSpec`` (or is another
            ``SpecLink``), or ``arguments`` is not a mapping of names, or names
            a read the target does not take or that its ``kwargs`` fills.
    """

    spec: AffordanceDeclarer
    arguments: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Copied into a read-only view, so the declaration cannot change under a cached binding.
        if not isinstance(self.spec, AffordanceDeclarer) or isinstance(self.spec, SpecLink):
            raise ImproperlyConfigured(
                f"SpecLink.spec must be a ServiceSpec; got {type(self.spec).__name__}."
            )
        arguments: Any = self.arguments
        if not isinstance(arguments, Mapping):
            raise ImproperlyConfigured(
                "SpecLink.arguments must be a mapping of read -> output field; got "
                f"{type(arguments).__name__}."
            )
        for read, name in arguments.items():
            if not isinstance(read, str) or not read or not isinstance(name, str) or not name:
                raise ImproperlyConfigured(
                    "SpecLink.arguments maps a read's name to an output field's name, both "
                    f"non-empty strings; got {read!r}: {name!r}."
                )
        reads = self.spec.link_reads()
        stray = sorted(set(arguments) - set(reads))
        if stray:
            raise ImproperlyConfigured(
                f"SpecLink.arguments binds {stray}, which the linked spec does not read from a "
                f"row: it reads {list(reads)}. A read its kwargs fills is the "
                "provider's, and a Validator field is never bound."
            )
        object.__setattr__(self, "arguments", MappingProxyType(dict(arguments)))

    @property
    def affordances(self) -> Sequence[Affordance] | None:
        """The linked spec's conditions, so a link answers as the bare spec does."""
        return self.spec.affordances

    def link_reads(self) -> tuple[str, ...]:
        """The linked spec's reads."""
        return self.spec.link_reads()
