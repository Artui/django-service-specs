from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.schema.spec_caller_input_schema import spec_caller_input_schema
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.build_call_context import build_call_context
from django_service_specs.types.call_transport import call_transport
from django_service_specs.types.provider_keys import ProviderKeys
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, TENANT_SEEDS, Record, make_user, note_by_pk, notes_of
from tests.specs.utils import Foreign

REQUIRED = ["This field is required."]
POLICIES = [UnknownArguments.REJECT, UnknownArguments.IGNORE]


class Fields(Validator):
    """Declares the parameters it is given and passes its arguments through."""

    def __init__(self, *parameters: Parameter) -> None:
        self.declared = Parameters.of(*parameters)

    def parameters(self) -> Parameters:
        return self.declared

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


def _required(name: str, kind: str = "string", **kwargs: Any) -> Parameter:
    return Parameter(name, kind, required=True, **kwargs)


def _title_and_owner() -> Fields:
    return Fields(_required("title"), _required("owner", "integer"))


class _Project(TypedDict):
    project: int


class _DecliningProject(TypedDict):
    project: int | UnsetType


class _Owner(TypedDict):
    owner: int


class _DecliningOwner(TypedDict):
    owner: int | UnsetType


class _DecliningPk(TypedDict):
    pk: int | UnsetType


def fills_project() -> _Project:
    return {"project": 1}


def declines_project() -> _DecliningProject:
    return {"project": 1}


def fills_owner() -> _Owner:
    return {"owner": 1}


def declines_owner() -> _DecliningOwner:
    return {"owner": 1}


def declines_pk() -> _DecliningPk:
    return {"pk": 1}


def untyped() -> dict[str, Any]:
    """A provider whose return names no keys, so it may fill every parameter its values reach."""
    return {}


def requires_project(*, project: int) -> dict[str, Any]:
    """An untyped provider taking the read ``project`` by name, only the caller can hand it."""
    return {}


def requires_pk(*, pk: int) -> dict[str, Any]:
    """An untyped provider taking the read ``pk`` by name, which only the caller can hand it."""
    return {}


PROJECT = Parameters.of(_required("project", "integer"))
OWNER = Parameters.of(_required("owner", "integer"))


def _target(**kwargs: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, **kwargs)


def _service(**kwargs: Any) -> ServiceSpec:
    return ServiceSpec(service=Record(), permissions=OPEN, **kwargs)


def _many(**kwargs: Any) -> ServiceSpec:
    return _service(
        many=True, validator=kwargs.pop("validator", None) or _title_and_owner(), **kwargs
    )


# Each spec a transport could describe, built on demand so the app registry
# is ready, and the seeds it is dispatched with.
FLAT: dict[str, tuple[Callable[[], ServiceSpec | SelectorSpec], PoolSeeds]] = {
    "selector": (
        lambda: SelectorSpec(
            kind=SelectorKind.LIST,
            selector=notes_of,
            permissions=OPEN,
            reads=Parameters.of(Parameter("search", "string"), _required("tag")),
        ),
        DEFAULT_POOL_SEEDS,
    ),
    "selector-untyped-kwargs": (
        lambda: SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=note_by_pk,
            permissions=OPEN,
            reads=PK,
            kwargs=untyped,
        ),
        DEFAULT_POOL_SEEDS,
    ),
    "service-with-target": (
        lambda: _service(validator=_title_and_owner(), instance_selector_spec=_target()),
        DEFAULT_POOL_SEEDS,
    ),
    "typed-kwargs-fills-a-read": (
        lambda: _service(reads=PROJECT, kwargs=fills_project, validator=_title_and_owner()),
        DEFAULT_POOL_SEEDS,
    ),
    "typed-kwargs-declines-a-read": (
        lambda: _service(reads=PROJECT, kwargs=declines_project),
        DEFAULT_POOL_SEEDS,
    ),
    "spec-kwargs-declines-pk-the-target-reads": (
        lambda: _service(kwargs=declines_pk, instance_selector_spec=_target()),
        DEFAULT_POOL_SEEDS,
    ),
    "target-kwargs-untyped": (
        lambda: _service(reads=PROJECT, instance_selector_spec=_target(kwargs=untyped)),
        DEFAULT_POOL_SEEDS,
    ),
    "input-data-fills-a-field": (
        lambda: _service(validator=_title_and_owner(), input_data=fills_owner),
        DEFAULT_POOL_SEEDS,
    ),
    "input-data-declines-a-field": (
        lambda: _service(
            reads=Parameters.of(_required("note", "integer")),
            validator=_title_and_owner(),
            input_data=declines_owner,
        ),
        DEFAULT_POOL_SEEDS,
    ),
    "input-data-untyped": (
        lambda: _service(reads=PROJECT, validator=_title_and_owner(), input_data=untyped),
        DEFAULT_POOL_SEEDS,
    ),
    "reflected-read-named-for-a-registered-seed": (
        lambda: _service(reads=Parameters.of(_required("tenant", reflected=True), _required("q"))),
        TENANT_SEEDS,
    ),
    "reflected-read-named-for-an-unregistered-seed": (
        lambda: _service(reads=Parameters.of(_required("tenant", reflected=True), _required("q"))),
        DEFAULT_POOL_SEEDS,
    ),
    "field-named-for-a-registered-seed": (
        lambda: _service(validator=Fields(_required("tenant"), _required("title"))),
        TENANT_SEEDS,
    ),
    "partial-with-a-filled-read": (
        lambda: _service(
            reads=PROJECT,
            kwargs=fills_project,
            validator=_title_and_owner(),
            partial=True,
            instance_selector_spec=_target(),
        ),
        DEFAULT_POOL_SEEDS,
    ),
}

MANY: dict[str, tuple[Callable[[], ServiceSpec | SelectorSpec], PoolSeeds]] = {
    "many-with-a-read": (lambda: _many(reads=PROJECT), DEFAULT_POOL_SEEDS),
    "many-untyped-kwargs": (lambda: _many(reads=PROJECT, kwargs=untyped), DEFAULT_POOL_SEEDS),
    "many-typed-kwargs-fills-a-read": (
        lambda: _many(reads=PROJECT, kwargs=fills_project),
        DEFAULT_POOL_SEEDS,
    ),
    "many-input-data-fills-a-row-field": (
        lambda: _many(reads=PROJECT, input_data=fills_owner),
        DEFAULT_POOL_SEEDS,
    ),
    "many-input-data-untyped": (
        lambda: _many(reads=OWNER, input_data=untyped),
        DEFAULT_POOL_SEEDS,
    ),
    "many-partial": (
        lambda: _many(reads=PROJECT, partial=True, input_data=fills_owner),
        DEFAULT_POOL_SEEDS,
    ),
    "many-row-field-named-for-a-registered-seed": (
        lambda: _many(validator=Fields(_required("tenant"), _required("title"))),
        TENANT_SEEDS,
    ),
}


# A provider requiring a read it may fill. Kept out of ``FLAT`` and ``MANY``,
# which the transports' readings from before they adopted this are held to:
# django-spec-agents' relaxed such a read.
REQUIRING: dict[str, tuple[Callable[[], ServiceSpec | SelectorSpec], PoolSeeds]] = {
    "selector-kwargs-requires-its-read": (
        lambda: SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=note_by_pk,
            permissions=OPEN,
            reads=PK,
            kwargs=requires_pk,
        ),
        DEFAULT_POOL_SEEDS,
    ),
    "target-kwargs-requires-its-read": (
        lambda: _service(
            reads=PROJECT, kwargs=untyped, instance_selector_spec=_target(kwargs=requires_pk)
        ),
        DEFAULT_POOL_SEEDS,
    ),
    "input-data-requires-a-read-beside-an-untyped-kwargs": (
        lambda: _service(
            reads=PROJECT, kwargs=untyped, validator=_title_and_owner(), input_data=requires_project
        ),
        DEFAULT_POOL_SEEDS,
    ),
    "many-untyped-kwargs-requires-its-read": (
        lambda: _many(reads=PROJECT, kwargs=requires_project),
        DEFAULT_POOL_SEEDS,
    ),
}


def _build(cases: Mapping[str, Any], case: str) -> tuple[ServiceSpec | SelectorSpec, PoolSeeds]:
    factory, seeds = cases[case]
    return factory(), seeds


def _row(schema: Mapping[str, Any], name: str = "items") -> dict[str, Any]:
    return schema["properties"][name]["items"]


# --- the top level ----------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("seat", ["kwargs", "input_data"])
def test_a_many_spec_s_list_is_offered_and_required_beside_an_untyped_provider(
    seat: str,
) -> None:
    # Dispatch demands the list from the caller, and no provider reaches it.
    spec = _many(**{seat: lambda: {"items": [1]}})

    assert "items" not in server_owned_keys(spec)
    schema = spec_caller_input_schema(spec)

    assert "items" in schema["properties"]
    assert schema["required"] == ["items"]
    assert _refused_absent(spec, DEFAULT_POOL_SEEDS, {}) == {"items"}


def test_a_many_spec_s_list_is_offered_where_a_mount_registers_a_seed_of_its_name() -> None:
    # The seed makes ``server_owned_keys`` list the name.
    spec = _many(many_argument="tenant")

    assert "tenant" in server_owned_keys(spec, pool_seeds=TENANT_SEEDS)
    schema = spec_caller_input_schema(spec, pool_seeds=TENANT_SEEDS)

    assert schema["required"] == ["tenant"]


def test_a_read_a_typed_kwargs_fills_is_not_offered() -> None:
    spec = _service(reads=PROJECT, kwargs=fills_project, validator=_title_and_owner())

    schema = spec_caller_input_schema(spec)

    assert "project" not in schema["properties"]
    assert schema["required"] == ["title", "owner"]


def test_a_reflected_read_named_for_a_registered_seed_is_withheld_only_under_those_seeds() -> None:
    # Builds whatever the seeds: ``reflected`` is read against the call's own ``pool_seeds``.
    spec = _service(reads=Parameters.of(_required("tenant", reflected=True)))

    assert spec_caller_input_schema(spec)["required"] == ["tenant"]
    assert spec_caller_input_schema(spec, pool_seeds=TENANT_SEEDS) == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_a_validator_field_named_for_a_registered_seed_is_offered() -> None:
    spec = _service(validator=Fields(_required("tenant")))

    schema = spec_caller_input_schema(spec, pool_seeds=TENANT_SEEDS)

    assert schema["required"] == ["tenant"]
    assert "tenant" in schema["properties"]


def test_bound_and_withheld_server_arguments_are_not_offered() -> None:
    spec = _service(
        reads=Parameters.of(
            _required("project", "integer"), Parameter("scope", "string"), _required("q")
        )
    )
    server = ServerArguments(values={"project": 3}, withheld=frozenset({"scope"}))

    schema = spec_caller_input_schema(spec, server_arguments=server)

    assert list(schema["properties"]) == ["q"]
    assert schema["required"] == ["q"]


def test_a_read_a_provider_may_decline_is_offered_and_not_required() -> None:
    spec = _service(reads=PROJECT, kwargs=declines_project)

    schema = spec_caller_input_schema(spec)

    assert "project" in schema["properties"]
    assert "required" not in schema


def test_a_selector_spec_s_reads_beside_an_untyped_kwargs_are_offered_and_none_required() -> None:
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, kwargs=untyped)

    schema = spec_caller_input_schema(spec)

    assert list(schema["properties"]) == ["pk"]
    assert "required" not in schema


@pytest.mark.parametrize(
    ("case", "required"),
    [
        pytest.param("selector-kwargs-requires-its-read", ["pk"], id="selector-spec"),
        pytest.param("target-kwargs-requires-its-read", ["pk"], id="target-selector"),
        pytest.param(
            "input-data-requires-a-read-beside-an-untyped-kwargs", ["project"], id="input-data"
        ),
        pytest.param("many-untyped-kwargs-requires-its-read", ["items", "project"], id="many"),
    ],
)
def test_a_read_a_provider_requires_itself_stays_required(case: str, required: list[str]) -> None:
    # The provider may fill it, but is handed only the caller's reads.
    spec, seeds = _build(REQUIRING, case)

    assert sorted(spec_caller_input_schema(spec, pool_seeds=seeds)["required"]) == required


def test_a_key_the_spec_s_kwargs_may_decline_leaves_the_target_s_read_required() -> None:
    # Per seat: the spec's ``kwargs`` reaches the spec's reads, never the lookup's.
    spec = _service(kwargs=declines_pk, instance_selector_spec=_target())

    assert spec_caller_input_schema(spec)["required"] == ["pk"]


@pytest.mark.parametrize(
    ("provider", "required"),
    [
        pytest.param(declines_owner, ["note", "title"], id="typed-declinable"),
        pytest.param(untyped, ["note"], id="untyped"),
    ],
)
def test_a_validator_field_input_data_may_fill_is_offered_and_not_required(
    provider: Callable[..., Any], required: list[str]
) -> None:
    # ``note`` is a read, in the spec's own seat: ``input_data`` relaxes none of it.
    spec = _service(
        reads=Parameters.of(_required("note", "integer")),
        validator=_title_and_owner(),
        input_data=provider,
    )

    schema = spec_caller_input_schema(spec)

    assert list(schema["properties"]) == ["note", "title", "owner"]
    assert schema["required"] == required


# --- each row of a ``many`` spec ---------------------------------------------------------


@pytest.mark.parametrize("name", ["items", "rows"])
def test_a_row_field_a_typed_input_data_fills_is_not_offered_in_any_row(name: str) -> None:
    schema = spec_caller_input_schema(_many(input_data=fills_owner, many_argument=name))

    assert list(_row(schema, name)["properties"]) == ["title"]
    assert _row(schema, name)["required"] == ["title"]


def test_a_row_field_a_typed_input_data_may_decline_is_offered_and_not_required() -> None:
    schema = spec_caller_input_schema(_many(input_data=declines_owner))

    assert list(_row(schema)["properties"]) == ["title", "owner"]
    assert _row(schema)["required"] == ["title"]


def test_beside_an_untyped_input_data_a_row_requires_nothing() -> None:
    schema = spec_caller_input_schema(_many(input_data=untyped))

    assert list(_row(schema)["properties"]) == ["title", "owner"]
    assert "required" not in _row(schema)


def test_a_row_s_relaxing_stays_out_of_the_top_level() -> None:
    # ``input_data`` reaches the rows alone: a read sharing a row field's name stays required.
    schema = spec_caller_input_schema(_many(reads=OWNER, input_data=untyped))

    assert schema["required"] == ["owner", "items"]


def test_a_read_bound_by_the_server_leaves_a_row_field_of_its_name_offered() -> None:
    spec = _many(reads=OWNER)

    schema = spec_caller_input_schema(spec, server_arguments=ServerArguments(values={"owner": 1}))

    assert "owner" not in schema["properties"]
    assert schema["required"] == ["items"]
    assert list(_row(schema)["properties"]) == ["title", "owner"]
    assert _row(schema)["required"] == ["title", "owner"]


def test_a_registered_seed_leaves_a_row_field_of_its_name_offered() -> None:
    # Builds: ``server_owned_keys`` keeps the seed's name on a ``many`` spec.
    spec = _many(validator=Fields(_required("tenant"), _required("title")))

    schema = spec_caller_input_schema(spec, pool_seeds=TENANT_SEEDS)

    assert "tenant" in server_owned_keys(spec, pool_seeds=TENANT_SEEDS)
    assert _row(schema)["required"] == ["tenant", "title"]


def test_an_untyped_kwargs_leaves_every_row_as_declared() -> None:
    # It may fill the read ``owner``, which a row field shares.
    spec = _many(reads=OWNER, kwargs=untyped)

    schema = spec_caller_input_schema(spec)

    assert schema["required"] == ["items"]
    assert _row(schema)["required"] == ["title", "owner"]
    assert _row(schema) == _row(spec_input_schema(spec))


def test_a_partial_many_spec_withholds_a_filled_row_field_and_requires_nothing_in_a_row() -> None:
    spec = _many(reads=PROJECT, partial=True, input_data=fills_owner)

    schema = spec_caller_input_schema(spec)

    assert schema["required"] == ["project", "items"]
    assert _row(schema) == {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("policy", "closed"), [(UnknownArguments.REJECT, True), (UnknownArguments.IGNORE, False)]
)
def test_the_unknown_argument_policy_closes_both_levels_or_neither(
    policy: UnknownArguments, closed: bool
) -> None:
    schema = spec_caller_input_schema(_many(input_data=fills_owner), unknown_arguments=policy)

    assert ("additionalProperties" in schema) is closed
    assert ("additionalProperties" in _row(schema)) is closed


@pytest.mark.parametrize("many", [False, True], ids=["flat", "many"])
def test_a_spec_source_is_described_as_the_spec_it_compiles_to(many: bool) -> None:
    # A ``many`` one too: its rows are read off the compiled spec.
    spec = _many(input_data=fills_owner) if many else _service(reads=PROJECT, kwargs=fills_project)

    assert spec_caller_input_schema(Foreign(spec)) == spec_caller_input_schema(spec)


def test_spec_input_schema_still_lists_what_the_server_fills() -> None:
    spec = _service(reads=PROJECT, kwargs=fills_project)

    spec_caller_input_schema(spec)

    assert spec_input_schema(spec)["required"] == ["project"]


def test_a_many_spec_whose_input_data_fills_a_read_is_refused() -> None:
    # Why ``server_owned_keys`` may name ``input_data``'s keys at a ``many`` spec's top level.
    with pytest.raises(ImproperlyConfigured, match=r"input_data is annotated to fill \['owner'\]"):
        _many(reads=OWNER, input_data=fills_owner)


class _Counting(Fields):
    def __init__(self, *parameters: Parameter) -> None:
        super().__init__(*parameters)
        self.asked = 0

    def parameters(self) -> Parameters:
        self.asked += 1
        return super().parameters()


def test_the_declaration_is_read_on_every_call() -> None:
    validator = _Counting(_required("title"))
    spec = _many(validator=validator)

    spec_caller_input_schema(spec)
    first = validator.asked
    spec_caller_input_schema(spec)

    assert first > 0
    assert validator.asked == 2 * first


# --- agreement with dispatch ------------------------------------------------------------


def _refused_absent(
    spec: ServiceSpec | SelectorSpec,
    pool_seeds: PoolSeeds,
    arguments: Mapping[str, Any],
    call_context: dict[str, Any] | None = None,
) -> set[str]:
    try:
        check_call(
            spec,
            principal=make_user("ada"),
            arguments=arguments,
            pool_seeds=pool_seeds,
            call_context=call_context,
        )
    except InvalidArguments as refused:
        assert all(message == REQUIRED for message in refused.detail.values())
        return set(refused.detail)
    return set()


@pytest.mark.django_db
@pytest.mark.parametrize("case", [*FLAT, *MANY, *REQUIRING])
def test_the_top_level_requires_exactly_what_check_call_refuses_absent(case: str) -> None:
    cases = {**FLAT, **MANY, **REQUIRING}
    spec, seeds = _build(cases, case)

    required = spec_caller_input_schema(spec, pool_seeds=seeds).get("required", [])

    assert set(required) == _refused_absent(spec, seeds, {})


def answers_every_row_field() -> dict[str, Any]:
    """An untyped ``input_data`` that answers each field, so a row leaving one out still runs."""
    return {"title": "server's", "owner": 7}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider",
    [None, fills_owner, declines_owner, answers_every_row_field],
    ids=["none", "typed-filled", "typed-declinable", "untyped"],
)
def test_a_row_omitting_a_relaxed_field_is_dispatched_and_one_omitting_a_required_field_is_refused(
    provider: Callable[..., Any] | None,
) -> None:
    # Each offered field left out of the second row alone: dispatch refuses it there, at its index.
    spec = _many(input_data=provider)
    row = _row(spec_caller_input_schema(spec))
    whole = {"title": "a", "owner": 2}
    for name in row["properties"]:
        arguments = {"items": [whole, {k: v for k, v in whole.items() if k != name}]}
        if name not in row.get("required", []):
            dispatch(spec, principal=make_user(f"ada-{name}"), arguments=arguments)
            continue
        with pytest.raises(InvalidArguments) as caught:
            dispatch(spec, principal=make_user(f"bob-{name}"), arguments=arguments)
        assert caught.value.detail == {"items": {1: {name: REQUIRED}}}


def _refused_in_row_zero(
    spec: ServiceSpec, pool_seeds: PoolSeeds, unknown_arguments: UnknownArguments
) -> set[str]:
    # A row is checked once the top level passes.
    top = spec_caller_input_schema(spec, pool_seeds=pool_seeds).get("required", [])
    arguments = {name: 1 for name in top if name != spec.many_argument}
    arguments[spec.many_argument] = [{}]
    try:
        check_call(
            spec,
            principal=make_user("ada"),
            arguments=arguments,
            pool_seeds=pool_seeds,
            unknown_arguments=unknown_arguments,
        )
    except InvalidArguments as refused:
        rows = refused.detail[spec.many_argument]
        assert list(rows) == [0]
        assert all(message == REQUIRED for message in rows[0].values())
        return set(rows[0])
    return set()


@pytest.mark.django_db
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("case", list(MANY))
def test_a_row_requires_exactly_what_check_call_refuses_in_row_zero(
    case: str, policy: UnknownArguments
) -> None:
    spec, seeds = _build(MANY, case)
    assert isinstance(spec, ServiceSpec)

    row = _row(
        spec_caller_input_schema(spec, pool_seeds=seeds, unknown_arguments=policy),
        spec.many_argument,
    )

    assert set(row.get("required", [])) == _refused_in_row_zero(spec, seeds, policy)


# --- the transports' own readings -------------------------------------------------------
#
# Pasted with only their kernel-level arithmetic, so the kernel can say it
# reads a spec as each transport did before the function existed, without
# installing one. Each cites the source it was read from.


def mcp_reference(
    spec: ServiceSpec | SelectorSpec,
    *,
    server_arguments: ServerArguments,
    unknown_arguments: UnknownArguments,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
) -> dict[str, Any]:
    """django-spec-mcp's tool input schema, less its paging."""
    schema = dict(spec_input_schema(spec, unknown_arguments=unknown_arguments))
    withheld = server_arguments.names() | server_owned_keys(spec, pool_seeds=pool_seeds)
    properties = {n: f for n, f in (schema.get("properties") or {}).items() if n not in withheld}
    schema["properties"] = properties
    unasked = withheld | provider_reached(spec)
    required = [n for n in schema.pop("required", []) if n not in unasked]
    if required:
        schema["required"] = required
    return schema


def agents_reference(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    server_names: frozenset[str],
    unknown_arguments: UnknownArguments,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
) -> dict[str, Any]:
    """django-spec-agents' tool schema of a spec, less its pagination and schema fragment."""
    compiled = kernel_spec(spec)
    schema = _agents_without(
        spec_input_schema(compiled, unknown_arguments=unknown_arguments),
        server_owned_keys(compiled, pool_seeds=pool_seeds),
    )
    declinable: set[str] = set()
    for names, keys in [*_agents_read_seats(compiled), *_agents_validator_seats(compiled)]:
        declinable |= names if keys is None else names & keys.declinable
    required = [name for name in schema.get("required", []) if name not in declinable]
    if required != schema.get("required", []):
        schema = {key: value for key, value in schema.items() if key != "required"}
        if required:
            schema["required"] = required
    return _agents_without(schema, server_names)


def _agents_without(schema: dict[str, Any], names: frozenset[str]) -> dict[str, Any]:
    """``_without`` at :2274 of the same file."""
    if not names:
        return schema
    cut: dict[str, Any] = {key: value for key, value in schema.items() if key != "required"}
    cut["properties"] = {
        key: value for key, value in schema.get("properties", {}).items() if key not in names
    }
    required = [name for name in schema.get("required", []) if name not in names]
    if required:
        cut["required"] = required
    return cut


def _agents_read_seats(
    compiled: ServiceSpec | SelectorSpec,
) -> list[tuple[frozenset[str], ProviderKeys | None]]:
    """``_read_seats`` at :2377 of the same file."""
    seats = [(compiled.reads.names(), provider_keys(compiled.kwargs))]
    target = compiled.target_selector_spec() if isinstance(compiled, ServiceSpec) else None
    if target is not None:
        seats.append((target.reads.names(), provider_keys(target.kwargs)))
    return seats


def _agents_validator_seats(
    compiled: ServiceSpec | SelectorSpec,
) -> list[tuple[frozenset[str], ProviderKeys | None]]:
    """``_validator_seats`` at :2398 of the same file."""
    if isinstance(compiled, ServiceSpec) and compiled.validator is not None and not compiled.many:
        return [(compiled.validator.parameters().names(), provider_keys(compiled.input_data))]
    return []


def rest_reference(spec: ServiceSpec | SelectorSpec) -> dict[str, Any]:
    """django-spec-rest's OPTIONS description of a spec, on a route capturing nothing."""
    owned = server_owned_keys(spec, pool_seeds=DEFAULT_POOL_SEEDS)
    target = spec.target_selector_spec() if isinstance(spec, ServiceSpec) else None
    if target is not None:
        owned |= target.parameters().names()
    sent = Parameters.of(*(param for param in spec.parameters() if param.name not in owned))
    return parameters_schema(sent, unknown_arguments=UnknownArguments.IGNORE)


SERVER_ARGUMENTS = [
    pytest.param(None, id="unbound"),
    pytest.param(ServerArguments(values={"q": "x"}, withheld=frozenset({"project"})), id="bound"),
]


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("server", SERVER_ARGUMENTS)
@pytest.mark.parametrize("case", FLAT)
def test_off_many_it_is_the_mcp_and_the_agents_reading(
    case: str, server: ServerArguments | None, policy: UnknownArguments
) -> None:
    spec, seeds = _build(FLAT, case)
    names = server.names() if server is not None else frozenset()

    schema = spec_caller_input_schema(
        spec, pool_seeds=seeds, server_arguments=server, unknown_arguments=policy
    )

    assert schema == mcp_reference(
        spec,
        server_arguments=server or ServerArguments(),
        unknown_arguments=policy,
        pool_seeds=seeds,
    )
    assert schema == agents_reference(
        spec, server_names=names, unknown_arguments=policy, pool_seeds=seeds
    )


@pytest.mark.parametrize("case", MANY)
def test_on_a_many_spec_the_transports_readings_part_from_it_only_in_the_rows(case: str) -> None:
    spec, seeds = _build(MANY, case)
    assert isinstance(spec, ServiceSpec)

    schema = spec_caller_input_schema(spec, pool_seeds=seeds)
    mcp = mcp_reference(
        spec,
        server_arguments=ServerArguments(),
        unknown_arguments=UnknownArguments.REJECT,
        pool_seeds=seeds,
    )
    agents = agents_reference(
        spec, server_names=frozenset(), unknown_arguments=UnknownArguments.REJECT, pool_seeds=seeds
    )

    # Neither transport reads a row: each leaves the rows as declared.
    assert _row(mcp) == _row(agents) == _row(spec_input_schema(spec))
    as_declared = {**schema["properties"], "items": mcp["properties"]["items"]}
    assert {**schema, "properties": as_declared} == mcp == agents


def _less_the_target(schema: dict[str, Any], spec: ServiceSpec | SelectorSpec) -> dict[str, Any]:
    target = spec.target_selector_spec() if isinstance(spec, ServiceSpec) else None
    names = target.parameters().names() if target is not None else frozenset()
    cut = {key: value for key, value in schema.items() if key != "required"}
    cut["properties"] = {k: v for k, v in schema["properties"].items() if k not in names}
    required = [name for name in schema.get("required", []) if name not in names]
    if required:
        cut["required"] = required
    return cut


@pytest.mark.parametrize(
    "case",
    [
        "selector",
        "service-with-target",
        "typed-kwargs-fills-a-read",
        "input-data-fills-a-field",
        "field-named-for-a-registered-seed",
        "many-with-a-read",
        "many-typed-kwargs-fills-a-read",
    ],
)
def test_where_no_provider_may_decline_and_nothing_is_partial_it_is_the_rest_reading(
    case: str,
) -> None:
    # Less the target's parameters, which the route reads off the URL.
    spec, _ = _build({**FLAT, **MANY}, case)

    schema = spec_caller_input_schema(spec, unknown_arguments=UnknownArguments.IGNORE)

    assert _less_the_target(schema, spec) == rest_reference(spec)


@pytest.mark.parametrize(
    ("case", "offered_and_required"),
    [
        pytest.param("typed-kwargs-declines-a-read", {"project"}, id="declinable"),
        pytest.param("selector-untyped-kwargs", {"pk"}, id="untyped"),
        pytest.param("input-data-untyped", {"title", "owner"}, id="untyped-input-data"),
        pytest.param("partial-with-a-filled-read", {"title", "owner"}, id="partial"),
    ],
)
def test_the_rest_reading_requires_what_a_provider_may_fill_and_a_partial_spec_s_fields(
    case: str, offered_and_required: set[str]
) -> None:
    spec, _ = _build(FLAT, case)

    schema = _less_the_target(
        spec_caller_input_schema(spec, unknown_arguments=UnknownArguments.IGNORE), spec
    )
    rest = rest_reference(spec)

    assert schema["properties"] == rest["properties"]
    assert set(rest["required"]) - set(schema.get("required", [])) == offered_and_required


# --- the context a transport describes under -----------------------------------------------


class _ToOneTransport(Validator):
    """Declares a required ``title``, and ``extra`` only to a call a ``cli`` transport stamped."""

    def __init__(self, *extra: Parameter) -> None:
        self.extra = extra

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        title = Parameter("title", "string", required=True)
        if call_transport(call_context) == "cli":
            return Parameters.of(title, *self.extra)
        return Parameters.of(title)

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


class _RowFills(TypedDict):
    extra: str


def _fills_a_row() -> _RowFills:
    return {"extra": "server's"}


class _RowMayFill(TypedDict):
    extra: str | UnsetType


def _may_fill_a_row() -> _RowMayFill:
    return {"extra": UNSET}


def _answers_extra() -> dict[str, Any]:
    return {"extra": "server's"}


_EXTRA = _required("extra")
_TITLE_ONLY = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}
_TITLE_AND_EXTRA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "extra": {"type": "string"}},
    "required": ["title", "extra"],
    "additionalProperties": False,
}


def test_a_field_declared_to_one_transport_is_offered_and_required_under_its_context() -> None:
    spec = _service(validator=_ToOneTransport(_EXTRA))

    assert spec_caller_input_schema(spec, call_context=build_call_context("cli")) == (
        _TITLE_AND_EXTRA
    )


@pytest.mark.parametrize(
    "call_context",
    [
        pytest.param(lambda: build_call_context("agent"), id="another-transport"),
        pytest.param(dict, id="an-unstamped-dict"),
        pytest.param(lambda: None, id="none"),
    ],
)
def test_a_field_declared_to_one_transport_is_not_offered_under_any_other_context(
    call_context: Callable[[], dict[str, Any] | None],
) -> None:
    spec = _service(validator=_ToOneTransport(_EXTRA))

    assert spec_caller_input_schema(spec, call_context=call_context()) == _TITLE_ONLY


def test_with_no_call_context_the_schema_is_the_declaration_made_to_no_call() -> None:
    # Literal, so the pin is the schema itself, not this function's answer to None.
    assert spec_caller_input_schema(_service(validator=_ToOneTransport(_EXTRA))) == _TITLE_ONLY
    assert spec_caller_input_schema(_many(validator=_ToOneTransport(_EXTRA))) == {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": _TITLE_ONLY, "maxItems": 1000},
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def test_a_seed_named_field_declared_only_to_a_transport_is_the_caller_s_under_its_context() -> (
    None
):
    # The ``server_owned_keys`` ask.
    spec = _service(validator=_ToOneTransport(Parameter("tenant", "string")))

    schema = spec_caller_input_schema(
        spec, pool_seeds=TENANT_SEEDS, call_context=build_call_context("cli")
    )

    assert schema["properties"].keys() == {"title", "tenant"}


def test_a_field_declared_only_to_a_transport_input_data_may_fill_is_not_required() -> None:
    # The ``provider_reached`` ask: an untyped ``input_data`` reaches every field.
    spec = _service(validator=_ToOneTransport(_EXTRA), input_data=_answers_extra)

    schema = spec_caller_input_schema(spec, call_context=build_call_context("cli"))

    assert schema["properties"].keys() == {"title", "extra"}
    assert "required" not in schema


def test_a_row_field_declared_only_to_a_transport_input_data_fills_is_not_offered() -> None:
    # The row's ask, read for what ``input_data`` is annotated to fill.
    spec = _many(validator=_ToOneTransport(_EXTRA), input_data=_fills_a_row)

    schema = spec_caller_input_schema(spec, call_context=build_call_context("cli"))

    row = schema["properties"][spec.many_argument]["items"]
    assert row["properties"].keys() == {"title"}
    assert row["required"] == ["title"]


def test_a_row_field_declared_only_to_a_transport_input_data_may_fill_is_not_required() -> None:
    # The row's ask, read for what ``input_data`` may fill.
    spec = _many(validator=_ToOneTransport(_EXTRA), input_data=_may_fill_a_row)

    schema = spec_caller_input_schema(spec, call_context=build_call_context("cli"))

    row = schema["properties"][spec.many_argument]["items"]
    assert row["properties"].keys() == {"title", "extra"}
    assert row["required"] == ["title"]


def test_a_partial_spec_requires_no_field_declared_only_to_a_transport() -> None:
    spec = _service(validator=_ToOneTransport(_EXTRA), partial=True)

    schema = spec_caller_input_schema(spec, call_context=build_call_context("cli"))

    assert schema["properties"].keys() == {"title", "extra"}
    assert "required" not in schema


@pytest.mark.parametrize("build", [_service, _many], ids=["single", "many"])
def test_a_validator_declaring_no_call_context_is_asked_as_before_under_one(
    build: Callable[..., ServiceSpec],
) -> None:
    # A keyword handed to one that never declared it raises TypeError.
    spec = build(validator=_title_and_owner(), input_data=_answers_extra)

    assert spec_caller_input_schema(
        spec, call_context=build_call_context("cli")
    ) == spec_caller_input_schema(spec)


@pytest.mark.parametrize(
    ("field", "declared", "refusal"),
    [
        pytest.param(
            Parameter("user", "string"),
            {},
            r"declares the parameter\(s\) \['user'\], which dispatch seeds itself",
            id="a-name-dispatch-seeds",
        ),
        pytest.param(
            Parameter("page", "integer"),
            {"reads": Parameters.of(Parameter("page", "integer"))},
            r"Parameters \['page'\] are declared by two sources",
            id="a-name-two-sources-declare",
        ),
        pytest.param(
            _EXTRA,
            {"kwargs": _fills_a_row},
            r"is annotated to fill \['extra'\], which ServiceSpec.validator declares, "
            r"and its values never reach",
            id="a-name-a-typed-kwargs-fills",
        ),
    ],
)
def test_a_declaration_only_a_transport_makes_is_refused_when_that_transport_asks(
    field: Parameter, declared: dict[str, Any], refusal: str
) -> None:
    # ``check_seeds`` asks with no context.
    spec = _service(validator=_ToOneTransport(field), **declared)

    assert check_seeds(spec) is None
    assert "title" in spec_caller_input_schema(spec)["properties"]
    with pytest.raises(ImproperlyConfigured, match=refusal):
        spec_caller_input_schema(spec, call_context=build_call_context("cli"))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("extra", "provider"),
    [
        pytest.param(_EXTRA, None, id="required"),
        pytest.param(_EXTRA, _answers_extra, id="beside-an-untyped-input-data"),
        pytest.param(Parameter("extra", "string"), None, id="optional"),
    ],
)
def test_under_a_context_it_requires_exactly_what_check_call_refuses_absent_under_it(
    extra: Parameter, provider: Callable[..., Any] | None
) -> None:
    spec = _service(validator=_ToOneTransport(extra), input_data=provider)
    call_context = build_call_context("cli")

    required = spec_caller_input_schema(spec, call_context=call_context).get("required", [])

    assert set(required) == _refused_absent(spec, DEFAULT_POOL_SEEDS, {}, call_context)


@pytest.mark.django_db
def test_a_field_offered_under_a_context_is_one_dispatch_takes_under_it() -> None:
    service = Record()
    spec = ServiceSpec(service=service, permissions=OPEN, validator=_ToOneTransport(_EXTRA))
    arguments = {"title": "Dune", "extra": "sent"}

    dispatch(
        spec,
        principal=make_user("ada"),
        arguments=arguments,
        call_context=build_call_context("cli"),
    )

    assert service.calls[-1]["data"] == arguments
    # The same arguments under no context name a field the declaration does not have.
    with pytest.raises(InvalidArguments) as refused:
        dispatch(spec, principal=make_user("bob"), arguments=arguments)
    assert set(refused.value.detail) == {"extra"}
