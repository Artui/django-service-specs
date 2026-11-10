from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch_app.models import Note

OPEN = (Unrestricted(),)
PK = Parameters.of(Parameter("pk", "integer", required=True))

# A registered seed whose value names the principal it was resolved for, so a
# test can tell it from anything a caller could have sent under the same name.
TENANT_SEEDS = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, user: f"tenant-of-{user.username}")


def make_user(username: str) -> Any:
    return get_user_model().objects.create_user(username=username)


def notes_of(*, user: Any) -> QuerySet[Note]:
    return Note.objects.filter(owner=user)


def note_by_pk(*, pk: int) -> QuerySet[Note]:
    # Unscoped on purpose: the object-level check is what refuses another owner's row.
    return Note.objects.filter(pk=pk)


class Refuse(PermissionCheck):
    """Refuses every principal at class level, in words no other check uses."""

    message = "Only editors may run this."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class OwnerOnly(PermissionCheck):
    """Admits every principal, then refuses a row it does not own; records each row it saw."""

    message = "Only the owner may touch this note."

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        self.rows.append(target)
        return bool(target.owner_id == principal.pk)


class Scoped(PermissionCheck):
    """Admits every principal; records each row and each scope it is asked about."""

    message = "Not within your scope."

    def __init__(self, *, refuse_scope: bool = False) -> None:
        self.refuse_scope = refuse_scope
        self.rows: list[Any] = []
        self.scopes: list[Any] = []

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        self.rows.append(target)
        return bool(target.owner_id == principal.pk)

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        # A set is recorded as its rows.
        self.scopes.append(None if scope is None else list(scope))
        return not self.refuse_scope


class Arguing(PermissionCheck):
    """Admits everything; records each question with the arguments it was handed."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, Mapping[str, Any] | None]] = []

    def _record(self, question: str, arguments: Mapping[str, Any] | None) -> bool:
        self.asked.append((question, arguments))
        return True

    def has_permission(
        self, principal: Any, spec: Any, *, arguments: Mapping[str, Any] | None = None
    ) -> bool:
        return self._record("has_permission", arguments)

    def has_object_permission(
        self, principal: Any, spec: Any, target: Any, *, arguments: Mapping[str, Any] | None = None
    ) -> bool:
        return self._record("has_object_permission", arguments)

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, arguments: Mapping[str, Any] | None = None
    ) -> bool:
        return self._record("has_scope_permission", arguments)

    def questions(self) -> list[tuple[str, dict[str, Any] | None]]:
        """What was asked, each mapping copied to a plain dict to compare."""
        return [(q, None if a is None else dict(a)) for q, a in self.asked]


class Offered(PermissionCheck):
    """Admits all; each question names the call's context and a ``tenant`` seed, recording both."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, Any, Any]] = []

    def has_permission(self, principal: Any, spec: Any, *, call_context: Any, tenant: Any) -> bool:
        self.asked.append(("has_permission", call_context, tenant))
        return True

    def has_object_permission(
        self, principal: Any, spec: Any, target: Any, *, call_context: Any, tenant: Any = None
    ) -> bool:
        self.asked.append(("has_object_permission", call_context, tenant))
        return True

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, call_context: Any, tenant: Any = None
    ) -> bool:
        self.asked.append(("has_scope_permission", call_context, tenant))
        return True


class SeedPerQuestion(PermissionCheck):
    """Admits everything; each question names a seed of its own, and records what it was handed."""

    def __init__(self) -> None:
        self.handed: list[tuple[str, Any]] = []

    def has_permission(self, principal: Any, spec: Any, *, club: Any) -> bool:
        self.handed.append(("has_permission", club))
        return True

    def has_object_permission(
        self, principal: Any, spec: Any, target: Any, *, row_club: Any
    ) -> bool:
        self.handed.append(("has_object_permission", row_club))
        return True

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, scope_club: Any
    ) -> bool:
        self.handed.append(("has_scope_permission", scope_club))
        return True


class Deactivated:
    """An authenticated principal with ``is_active`` false: ``is_deactivated`` reads it as one."""

    is_authenticated = True
    is_active = False

    def __str__(self) -> str:
        return "dormant"


class PositionalOnly(PermissionCheck):
    """Names a registered seed in each question's last positional slot, and records what it got."""

    def __init__(self) -> None:
        self.handed: list[tuple[str, Any]] = []

    def has_permission(self, principal: Any, club: Any) -> bool:
        self.handed.append(("has_permission", club))
        return True

    def has_object_permission(self, principal: Any, spec: Any, row_club: Any) -> bool:
        self.handed.append(("has_object_permission", row_club))
        return True

    def has_scope_permission(self, principal: Any, spec: Any, scope_club: Any) -> bool:
        self.handed.append(("has_scope_permission", scope_club))
        return True


def recorded_seeds(raising: BaseException | None = None) -> tuple[PoolSeeds, list[str]]:
    """``SeedPerQuestion``'s three seeds and one no check names, each recording when it resolves."""
    resolved: list[str] = []

    def resolver(name: str) -> Any:
        def resolve(*, user: Any) -> str:
            resolved.append(name)
            if raising is not None:
                raise raising
            return f"{name} of {user}"

        return resolve

    names = ("club", "row_club", "scope_club", "locale")
    return DEFAULT_POOL_SEEDS.extend(**{name: resolver(name) for name in names}), resolved


class Titled(Validator):
    """Declares a required title and strips it; records every call."""

    def __init__(self, returns: Mapping[str, Any] | None = None) -> None:
        self.returns = returns
        self.calls: list[tuple[dict[str, Any], ValidationContext]] = []

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("title", "string", required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.calls.append((dict(arguments), context))
        if self.returns is not None:
            return dict(self.returns)
        return {"title": arguments["title"].strip()}


class Listed(Titled):
    """Validates a many call's rows as one list, as a list serializer does."""

    def __init__(self, *, most: int = 10) -> None:
        super().__init__()
        self.most = most
        self.lists: list[tuple[dict[int, dict[str, Any]], ValidationContext, str]] = []

    def validated_many(
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        self.lists.append(({i: dict(row) for i, row in rows.items()}, context, many_argument))
        errors: dict[Any, Any] = {
            index: {"title": ["Not this one."]}
            for index, row in rows.items()
            if row.get("title") == "bad"
        }
        if len(rows) > self.most:
            errors[NON_FIELD_ERRORS] = [f"At most {self.most} rows."]
        if errors:
            raise InvalidArguments(errors)
        values = [{"title": row["title"].upper()} for row in rows.values()]
        return Validated(values={many_argument: values}, data=values, pool={"listed": self})


class Contextual(Presenter):
    """Renders a note as its title, and records the call's context it was handed with each value."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []

    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        return {"title": value.title}

    def presented(self, value: Any, context: Any) -> Any:
        self.contexts.append(context)
        return self.present(value)


class Titles(Presenter):
    """Renders a note as its title; records every value it was handed."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        self.seen.append(value)
        return {"title": value.title}


class Record:
    """A spec callable that records the keywords it received and returns ``returns``."""

    def __init__(self, returns: Any = None) -> None:
        self.returns = returns
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **pool: Any) -> Any:
        self.calls.append(pool)
        return self.returns


def shaping_refused(source: str, returned: str) -> str:
    """``shape_queryset``'s refusal, as it names the selector that returned a non-queryset."""
    return (
        "select_related / prefetch_related / annotations / extend_queryset / filter_set are "
        f"set on the spec but {source} returned {returned}, which is not a Django QuerySet. "
        "Drop the shaping fields or have the callable return a QuerySet."
    )


class NoteRows(Presenter):
    """Renders a note, or a mapping shaped like one, as its pk and title."""

    def output(self) -> Output:
        return Output((OutputField("id", "integer"), OutputField("title", "string")))

    def present(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {"id": value["id"], "title": value["title"]}
        return {"id": value.pk, "title": value.title}


# Renaming a note, with one condition of each kind, so every path that answers
# a selector spec's ``affordances`` is asked both: a condition on the row, and
# a callable over the seeds. ``EDIT`` declares none, so its answer is always
# available.
NOT_ARCHIVED = Affordance(
    code="note_archived", reason="An archived note cannot be renamed.", when=Q(archived=False)
)
BOOKS_OPEN = Affordance(
    code="books_closed", reason="Renaming is paused while the books close.", when=lambda: True
)
BOOKS_CLOSED = Affordance(
    code="books_closed", reason="Renaming is paused while the books close.", when=lambda: False
)
RENAME = ServiceSpec(service=Record(), permissions=OPEN, affordances=[NOT_ARCHIVED, BOOKS_OPEN])
EDIT = ServiceSpec(service=Record(), permissions=OPEN)
REFUSED_ARCHIVED = {
    "available": False,
    "code": "note_archived",
    "reason": "An archived note cannot be renamed.",
}
REFUSED_CLOSED = {
    "available": False,
    "code": "books_closed",
    "reason": "Renaming is paused while the books close.",
}

OWNER_NAME = Parameters.of(Parameter("owner", "string", required=True))


def returning_many(rows: Any, presenter: Any) -> tuple[ServiceSpec, Record]:
    """A ``returns_many`` spec whose one-argument service returns ``rows``, with the service."""
    service = Record(returns=rows)
    spec = ServiceSpec(
        service=service, permissions=OPEN, reads=OWNER_NAME, presenter=presenter, returns_many=True
    )
    return spec, service


def two_notes() -> list[Note]:
    ada = make_user("ada")
    return [Note.objects.create(owner=ada, title=title) for title in ("First", "Second")]


class AskedWith(Validator):
    """Declares ``fields``, opts into ``call_context``."""

    def __init__(self, *fields: Parameter) -> None:
        self.fields = fields or (Parameter("title", "string", required=True),)
        self.asked: list[dict[str, Any] | None] = []
        self.contexts: list[ValidationContext] = []

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        self.asked.append(call_context)
        return Parameters.of(*self.fields)

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        self.contexts.append(context)
        return dict(arguments)


A_CALL: dict[str, Any] = {"marked": True}
"""A call's context that ``DeclaredToACall`` declares its extra field to."""


class DeclaredToACall(Validator):
    """Declares ``title``, and ``extra`` only to a call whose ``call_context`` is marked."""

    def __init__(self, extra: Parameter) -> None:
        self.extra = extra

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        title = Parameter("title", "string")
        if call_context is not None and call_context.get("marked"):
            return Parameters.of(title, self.extra)
        return Parameters.of(title)

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


EVERY_ASK = ("single", "many")
"""The two cases that between them run every ask of a Validator's ``parameters`` inside a call.

``single`` has a provider and a field named like ``TENANT_SEEDS``' seed, so
the seed-named and provider paths ask; ``many`` asks for its rows. Every
service spec's call is prepared, so both run ``prepare_service``'s asks.
"""


def every_ask_case(case: str) -> tuple[ServiceSpec, AskedWith, dict[str, Any], Record]:
    """A spec for ``case``, its ``AskedWith``, the arguments it is called with, and its service."""
    service = Record()
    if case == "single":
        validator = AskedWith(
            Parameter("title", "string", required=True), Parameter("tenant", "string")
        )
        spec = ServiceSpec(
            service=service,
            permissions=OPEN,
            validator=validator,
            input_data=lambda: {"title": UNSET},
        )
        arguments: dict[str, Any] = {"title": "Dune", "tenant": "caller's"}
    else:
        validator = AskedWith()
        spec = ServiceSpec(service=service, permissions=OPEN, validator=validator, many=True)
        arguments = {spec.many_argument: [{"title": "Dune"}, {"title": "Emma"}]}
    validator.asked.clear()
    return spec, validator, arguments, service


class Tenancy:
    """A ``tenant`` seed counting its resolutions, and a spec whose check names it."""

    def __init__(self) -> None:
        self.resolved: list[object] = []
        self.seen: list[tuple[str, object]] = []
        self.pool_seeds = DEFAULT_POOL_SEEDS.extend(tenant=self.tenant)

    def tenant(self) -> object:
        self.resolved.append(object())
        return self.resolved[-1]

    def check(self) -> PermissionCheck:
        """Admits everyone, at the class level and on the row, recording the tenant each time."""
        seen = self.seen

        class _TenantCheck(PermissionCheck):
            def has_permission(self, principal: Any, spec: Any, *, tenant: object) -> bool:
                seen.append(("has_permission", tenant))
                return True

            def has_object_permission(
                self, principal: Any, spec: Any, target: Any, *, tenant: object
            ) -> bool:
                seen.append(("has_object_permission", tenant))
                return True

        return _TenantCheck()

    def spec(self, **extra: Any) -> ServiceSpec:
        """A service acting on the note named by ``pk``, each stage naming ``tenant``."""
        seen = self.seen

        def instance(*, pk: int, tenant: object) -> QuerySet[Note]:
            seen.append(("instance_selector", tenant))
            return Note.objects.filter(pk=pk)

        def service(*, instance: Note, tenant: object) -> Note:
            seen.append(("service", tenant))
            return instance

        return ServiceSpec(
            service=extra.pop("service", service),
            permissions=(self.check(),),
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=instance, reads=PK
            ),
            **extra,
        )

    def one_value(self) -> bool:
        """Whether the seed resolved once and every stage was handed that very object."""
        return len(self.resolved) == 1 and all(value is self.resolved[0] for _, value in self.seen)
