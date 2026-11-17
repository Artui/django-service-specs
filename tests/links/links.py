from __future__ import annotations

from typing import Any, TypedDict

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UnsetType
from tests.dispatch.utils import NOT_ARCHIVED, OPEN, Record, notes_of

PK = Parameter("pk", "integer", required=True)
TITLE = Parameter("title", "string")
TENANT = Parameter("tenant", "string", required=True)


class Tenant(TypedDict):
    tenant: str


def tenant_of() -> Tenant:
    return {"tenant": "acme"}


def untyped() -> dict[str, Any]:
    return {}


class MayDecline(TypedDict):
    tenant: str | UnsetType


def declining() -> MayDecline:
    return {"tenant": "acme"}


def needs_pk(*, pk: int) -> dict[str, Any]:
    return {"tenant": "acme"}


def target(*reads: Parameter, **fields: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=Record(), reads=Parameters(reads), **fields
    )


def service(*reads: Parameter, own: tuple[Parameter, ...] = (), **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=OPEN,
        instance_selector_spec=target(*reads) if reads else None,
        reads=Parameters(own),
        affordances=[NOT_ARCHIVED],
        **fields,
    )


RENAME = service(PK, own=(TITLE,))


class Rows(Presenter):
    """A note as its HANDLE ``id``, its ``title``, a HIDDEN ``owner_id`` and any extra fields."""

    def __init__(self, *extra: OutputField) -> None:
        self.extra = extra

    def output(self) -> Output:
        return Output(
            (
                OutputField("id", "integer", marking=FieldMarking.handle()),
                OutputField("title", "string"),
                OutputField("owner_id", "integer", marking=FieldMarking.hidden()),
                *self.extra,
            )
        )

    def present(self, value: Any) -> Any:
        return {"id": value.pk, "title": value.title, "owner_id": value.owner_id}


class NoOutput(Rows):
    def output(self) -> None:
        return None


class Declarer(AffordanceDeclarer):
    """An operation's conditions declared by something other than a ``ServiceSpec``."""

    @property
    def affordances(self) -> tuple[()]:
        return ()


def listing(affordances: Any, presenter: Presenter | None = None, **fields: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=notes_of,
        permissions=OPEN,
        presenter=Rows() if presenter is None else presenter,
        affordances=affordances,
        **fields,
    )
