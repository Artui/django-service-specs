from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.dispatch.utils import reach
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.validation.validator import Validator
from django_service_specs.validation.validator_parameters import validator_parameters


def spec_caller_input_schema(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    server_arguments: ServerArguments | None = None,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What a caller is asked to send ``spec``:
    [`spec_input_schema`][django_service_specs.schema.spec_input_schema.spec_input_schema] less what
    the server answers.

    ``spec_input_schema`` lists every parameter as declared, ``required``
    meaning the call needs the value from someone. This is the schema a
    transport advertises, so ``required`` means the caller, and it requires
    exactly what dispatch refuses the caller for leaving out
    (test_the_top_level_requires_exactly_what_check_call_refuses_absent):

    - **Withheld, from** ``properties`` **and** ``required``: every name
      [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
      lists for ``pool_seeds``, the seeds the transport dispatches with
      (test_a_read_a_typed_kwargs_fills_is_not_offered,
      test_a_reflected_read_named_for_a_registered_seed_is_withheld_only_under_those_seeds),
      so a Validator field named like a registered seed is still offered
      (test_a_validator_field_named_for_a_registered_seed_is_offered); and
      the ``names()`` of the transport's ``server_arguments``, bound and
      withheld alike
      (test_bound_and_withheld_server_arguments_are_not_offered). This does
      not check that binding: ``check_server_arguments`` does, once, when the
      transport is built. A ``many`` spec's list is the one name
      ``server_owned_keys`` lists that is not withheld: a provider annotated
      to fill it is refused when the spec is built, so it is listed only
      where a mount registers a seed of that name, which dispatch refuses
      (test_a_many_spec_s_list_is_offered_where_a_mount_registers_a_seed_of_its_name).
    - **Offered and not required**: a parameter a provider may fill,
      [`provider_reached`][django_service_specs.dispatch.provider_reached.provider_reached],
      the set the shape check relaxes, read seat by seat
      (test_a_read_a_provider_may_decline_is_offered_and_not_required,
      test_a_selector_spec_s_reads_beside_an_untyped_kwargs_are_offered_and_none_required,
      test_a_key_the_spec_s_kwargs_may_decline_leaves_the_target_s_read_required,
      test_a_validator_field_input_data_may_fill_is_offered_and_not_required).
      **Not a read a provider requires itself**: a provider is handed the
      caller's reads and the seeds, never another provider's answer, so
      dispatch demands it of the caller and it stays in ``required``
      (test_a_read_a_provider_requires_itself_stays_required).

    **On a** ``many`` **spec each row is read the same way**, by what
    ``input_data`` reaches there: it runs once per call and is merged over
    every row, so one ``items`` serves them all. A field it is annotated to
    fill leaves the row's ``properties``, since dispatch drops the caller's
    value for one once checked
    (test_a_row_field_a_typed_input_data_fills_is_not_offered_in_any_row),
    and one it may fill is offered and not required
    (test_a_row_field_a_typed_input_data_may_decline_is_offered_and_not_required,
    test_beside_an_untyped_input_data_a_row_requires_nothing). The two levels
    stay apart. A row's relaxing never reaches the top, where the list and
    the reads stay as dispatch demands them
    (test_a_row_s_relaxing_stays_out_of_the_top_level). Nor does the top's
    withheld set reach a row: ``check_server_arguments`` refuses binding a
    row field, a registered seed's name leaves a row field of that name the
    caller's, and ``kwargs`` is merged into the service's pool, never a row
    (test_a_read_bound_by_the_server_leaves_a_row_field_of_its_name_offered,
    test_a_registered_seed_leaves_a_row_field_of_its_name_offered,
    test_an_untyped_kwargs_leaves_every_row_as_declared). Dispatch agrees row
    by row
    (test_a_row_omitting_a_relaxed_field_is_dispatched_and_one_omitting_a_required_field_is_refused).

    ``partial`` is ``spec_input_schema``'s, applied first, and a ``required``
    left empty, at either level, is dropped, as ``spec_input_schema`` writes
    none for a spec requiring nothing
    (test_a_partial_many_spec_withholds_a_filled_row_field_and_requires_nothing_in_a_row).
    ``unknown_arguments`` closes both levels or neither, as dispatch does
    (test_the_unknown_argument_policy_closes_both_levels_or_neither).

    Off a ``many`` spec, the reading django-spec-mcp and django-spec-agents
    made of ``spec_input_schema`` before this existed
    (test_off_many_it_is_the_mcp_and_the_agents_reading), but for a read a
    provider requires itself, which django-spec-agents' reading relaxed;
    neither read a row
    (test_on_a_many_spec_the_transports_readings_part_from_it_only_in_the_rows).
    ``spec_input_schema`` itself is unchanged and still lists what the server
    fills (test_spec_input_schema_still_lists_what_the_server_fills). A
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] is
    described as the spec it compiles to
    (test_a_spec_source_is_described_as_the_spec_it_compiles_to). Read on
    every call, as ``parameters()`` is
    (test_the_declaration_is_read_on_every_call).

    **Describe-time unless handed a context.** With no ``call_context`` a
    Validator that declares it is handed ``None``, and ``server_owned_keys`` and
    ``provider_reached`` are read with no call's context
    (test_describe_time_readers_hand_none), so a field declared only to a
    transport is not offered
    (test_with_no_call_context_the_schema_is_the_declaration_made_to_no_call).
    A transport describing the spec under a context of its own, a stamped one
    above all, hands that dict, and it is the object every ask of the Validator
    is handed (test_a_reader_handed_a_context_hands_that_object_to_every_ask).
    The field is then offered there and nowhere else
    (test_a_field_declared_to_one_transport_is_offered_and_required_under_its_context,
    test_a_field_declared_to_one_transport_is_not_offered_under_any_other_context),
    and read as dispatch reads it under that dict: withheld, relaxed and
    required at each level by what its context declares
    (test_a_seed_named_field_declared_only_to_a_transport_is_the_caller_s_under_its_context,
    test_a_field_declared_only_to_a_transport_input_data_may_fill_is_not_required,
    test_a_row_field_declared_only_to_a_transport_input_data_fills_is_not_offered,
    test_a_row_field_declared_only_to_a_transport_input_data_may_fill_is_not_required,
    test_under_a_context_it_requires_exactly_what_check_call_refuses_absent_under_it).
    A Validator declaring no ``call_context`` is asked as before
    (test_a_validator_declaring_no_call_context_is_asked_as_before_under_one).
    No call need be under way: where a transport has none, the dict of
    ``build_call_context`` names it, with ``request`` and ``view`` ``None``.

    Raises:
        ImproperlyConfigured: a declaration that fails assembly, one a Validator
            makes only under the handed ``call_context`` included
            (test_a_declaration_only_a_transport_makes_is_refused_when_that_transport_asks).
    """
    spec = kernel_spec(spec)
    schema = spec_input_schema(spec, unknown_arguments=unknown_arguments, call_context=call_context)
    withheld = server_owned_keys(spec, pool_seeds=pool_seeds, call_context=call_context)
    if isinstance(spec, ServiceSpec) and spec.many:
        validator = cast(Validator, spec.validator)
        fields = validator_parameters(validator, call_context=call_context)
        owned, reached = reach(spec.input_data, fields)
        the_list = schema["properties"][spec.many_argument]
        the_list["items"] = _asked(the_list["items"], withheld=owned, relaxed=reached)
        withheld -= {spec.many_argument}
    if server_arguments is not None:
        withheld |= server_arguments.names()
    relaxed = provider_reached(spec, call_context=call_context)
    return _asked(schema, withheld=withheld, relaxed=relaxed)


def _asked(
    node: Mapping[str, Any], *, withheld: frozenset[str], relaxed: frozenset[str]
) -> dict[str, Any]:
    """``node`` less ``withheld``, with ``relaxed`` offered and not required."""
    asked = {key: value for key, value in node.items() if key != "required"}
    asked["properties"] = {
        name: fragment for name, fragment in node["properties"].items() if name not in withheld
    }
    required = [name for name in node.get("required", ()) if name not in withheld | relaxed]
    if required:
        asked["required"] = required
    return asked
