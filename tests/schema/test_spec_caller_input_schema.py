from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import TypedDict

from django_service_specs.dispatch.check_call import check_call
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
from django_service_specs.types.provider_keys import ProviderKeys
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from tests.dispatch.utils import OPEN, PK, TENANT_SEEDS, Record, make_user, note_by_pk, notes_of
from tests.specs.utils import Foreign

REQUIRED = ["This field is required."]


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


def _build(cases: Mapping[str, Any], case: str) -> tuple[ServiceSpec | SelectorSpec, PoolSeeds]:
    factory, seeds = cases[case]
    return factory(), seeds


def _row(schema: Mapping[str, Any], name: str = "items") -> dict[str, Any]:
    return schema["properties"][name]["items"]


# --- the top level ----------------------------------------------------------------------


def test_a_read_a_typed_kwargs_fills_is_not_offered() -> None:
    spec = _service(reads=PROJECT, kwargs=fills_project, validator=_title_and_owner())

    schema = spec_caller_input_schema(spec)

    assert "project" not in schema["properties"]
    assert schema["required"] == ["title", "owner"]


def test_a_reflected_read_named_for_a_registered_seed_is_withheld_only_under_those_seeds() -> None:
    # Builds whatever the seeds: ``reflected`` is read against the call's own
    # ``pool_seeds``, and an unregistered name is the caller's argument.
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


def test_a_key_the_spec_s_kwargs_may_decline_leaves_the_target_s_read_required() -> None:
    # Per seat: the spec's ``kwargs`` reaches the spec's reads, never the
    # lookup's, so its declinable ``pk`` relaxes nothing there.
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


def test_a_row_field_a_typed_input_data_fills_is_not_offered_in_any_row() -> None:
    schema = spec_caller_input_schema(_many(input_data=fills_owner))

    assert list(_row(schema)["properties"]) == ["title"]
    assert _row(schema)["required"] == ["title"]


def test_a_row_field_a_typed_input_data_may_decline_is_offered_and_not_required() -> None:
    schema = spec_caller_input_schema(_many(input_data=declines_owner))

    assert list(_row(schema)["properties"]) == ["title", "owner"]
    assert _row(schema)["required"] == ["title"]


def test_beside_an_untyped_input_data_a_row_requires_nothing() -> None:
    schema = spec_caller_input_schema(_many(input_data=untyped))

    assert list(_row(schema)["properties"]) == ["title", "owner"]
    assert "required" not in _row(schema)


def test_a_row_s_relaxing_stays_out_of_the_top_level() -> None:
    # ``input_data`` reaches the rows alone: a read sharing a row field's name
    # stays required, and so does the list.
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
    # Builds: ``server_owned_keys`` keeps the seed's name on a ``many`` spec,
    # and no seed check reads a row, whose field of that name is the caller's.
    spec = _many(validator=Fields(_required("tenant"), _required("title")))

    schema = spec_caller_input_schema(spec, pool_seeds=TENANT_SEEDS)

    assert "tenant" in server_owned_keys(spec, pool_seeds=TENANT_SEEDS)
    assert _row(schema)["required"] == ["tenant", "title"]


def test_an_untyped_kwargs_leaves_every_row_as_declared() -> None:
    # It may fill the read ``owner``, which a row field shares, and reaches
    # the service's pool alone: the row's ``owner`` stays required.
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
    # A ``many`` one too: its rows are read off the compiled spec, which a
    # declaration of another library's is not.
    spec = _many(input_data=fills_owner) if many else _service(reads=PROJECT, kwargs=fills_project)

    assert spec_caller_input_schema(Foreign(spec)) == spec_caller_input_schema(spec)


def test_spec_input_schema_still_lists_what_the_server_fills() -> None:
    spec = _service(reads=PROJECT, kwargs=fills_project)

    spec_caller_input_schema(spec)

    assert spec_input_schema(spec)["required"] == ["project"]


def test_a_many_spec_whose_input_data_fills_a_read_is_refused() -> None:
    # Why ``server_owned_keys`` may name ``input_data``'s keys at a ``many``
    # spec's top level: none of them can be a read there, so withholding them
    # withholds nothing dispatch demands. Refused when the spec is built.
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
    spec: ServiceSpec | SelectorSpec, pool_seeds: PoolSeeds, arguments: Mapping[str, Any]
) -> set[str]:
    try:
        check_call(spec, principal=make_user("ada"), arguments=arguments, pool_seeds=pool_seeds)
    except InvalidArguments as refused:
        assert all(message == REQUIRED for message in refused.detail.values())
        return set(refused.detail)
    return set()


@pytest.mark.django_db
@pytest.mark.parametrize("case", [*FLAT, *MANY])
def test_the_top_level_requires_exactly_what_check_call_refuses_absent(case: str) -> None:
    cases = {**FLAT, **MANY}
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
    # Each offered field left out of the second row alone: dispatch refuses
    # it there, at its index, exactly when the row's schema requires it.
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
    """django-spec-mcp's tool input schema, less its paging.

    ``django_spec_mcp/schema/kernel_tool_input_schema.py`` at ``b1e3904``,
    lines 58-69 and 79-84.
    """
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
    """django-spec-agents' tool schema of a spec, less its pagination and schema fragment.

    ``django_spec_agents/spec_tools/spec_toolset.py`` at ``72effcb``:
    ``_caller_schema`` (:2294), with ``_without(schema, server_names)``
    applied last as at :2246.
    """
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
    """django-spec-rest's OPTIONS description of a spec, on a route capturing nothing.

    ``django_spec_rest/views/spec_options.py`` at ``51e429d``: ``_described``
    (:134) over ``spec.parameters()``, its ``declared`` (:111), with an empty
    ``view.kwargs``, the default seeds and the edge's ``UNKNOWN_ARGUMENTS``,
    ``IGNORE`` (``dispatch/kernel_edge.py:120``).
    """
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
POLICIES = [UnknownArguments.REJECT, UnknownArguments.IGNORE]


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

    # Neither transport reads a row: each leaves the rows as declared, and so
    # asks for a field ``input_data`` fills.
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
    # Less the target's parameters, which the route reads off the URL. A
    # provider that only fills leaves both alike, since both withhold what it
    # fills; on a ``many`` spec here no ``input_data`` reaches a row, which
    # ``_described`` never reads.
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
