from __future__ import annotations

import enum
import importlib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db.models import Model

import django_service_specs
from django_service_specs import (
    Parameters,
    SelectorKind,
    SelectorSpec,
    UnknownArguments,
    Unrestricted,
    adispatch,
    check_arguments,
    check_call,
    dispatch,
    parameters_schema,
)

_PACKAGE = "django_service_specs"
_UNPINNED = object()


@dataclass(frozen=True)
class Pin:
    """What one name promises its importers. Every facet left out is not pinned."""

    leaf: str
    signature: str | None = None
    methods: Mapping[str, str] = field(default_factory=dict)
    abstract: frozenset[str] | None = None
    bases: tuple[str | type, ...] = ()
    members: Mapping[str, object] | None = None
    value: object = _UNPINNED
    instance_of: str | None = None
    leaf_only: bool = False
    bound: type | None = None
    parameter_of: str | None = None


def _fn(leaf: str, signature: str) -> Pin:
    return Pin(leaf, signature=signature)


def _error(leaf: str, signature: str, base: str | type) -> Pin:
    return Pin(leaf, signature=signature, bases=(base,))


def _enum(leaf: str, members: Mapping[str, object], mixin: type) -> Pin:
    return Pin(leaf, members=members, bases=(mixin,))


def _protocol(leaf: str, call: str) -> Pin:
    # A Protocol class's own signature is typing's placeholder and differs between Python versions.
    return Pin(leaf, methods={"__call__": call})


# Grouped by subpackage. Adding a name is one row.
SURFACE: dict[str, Pin] = {
    # --- affordances --------------------------------------------------------------------------
    "enforce_affordances": _fn(
        "affordances.enforce_affordances", "spec, pool, *, instance, reserved, call_context="
    ),
    "aenforce_affordances": _fn(
        "affordances.aenforce_affordances", "spec, pool, *, instance, reserved, call_context="
    ),
    "operation_affordances": _fn("affordances.operation_affordances", "spec"),
    "unmet_operation_affordance": _fn(
        "affordances.unmet_operation_affordance", "spec, pool, *, reserved, call_context="
    ),
    "aunmet_operation_affordance": _fn(
        "affordances.aunmet_operation_affordance", "spec, pool, *, reserved, call_context="
    ),
    # --- authorization ------------------------------------------------------------------------
    "resolve_principal": _fn("authorization.resolve_principal", "identifier"),
    # Subclassed by the adapter's permission check over DRF permission classes.
    "PermissionCheck": Pin(
        "authorization.permission_check",
        abstract=frozenset({"has_permission"}),
        methods={
            "has_permission": "(principal, spec)",
            "has_object_permission": "(principal, spec, target)",
            "has_scope_permission": "(principal, spec, scope)",
        },
    ),
    "Unrestricted": Pin(
        "authorization.unrestricted",
        bases=("PermissionCheck",),
        methods={"has_permission": "(principal, spec)"},
    ),
    # The adapter subclasses these two beside DRF's PermissionDenied.
    "NotPermitted": _error("authorization.not_permitted", "message=", "DispatchError"),
    "PrincipalUnavailable": _error(
        "authorization.principal_unavailable", "message=", "DispatchError"
    ),
    # --- dispatch -----------------------------------------------------------------------------
    "dispatch": _fn(
        "dispatch.dispatch",
        "spec, *, principal, arguments, grant=, seeds=, pool_seeds=, unknown_arguments=, "
        "progress=, target=, extra_kwargs=, call_context=",
    ),
    "adispatch": _fn(
        "dispatch.adispatch",
        "spec, *, principal=, principal_id=, arguments, grant=, seeds=, pool_seeds=, "
        "unknown_arguments=, progress=, target=, extra_kwargs=, call_context=",
    ),
    "check_call": _fn(
        "dispatch.check_call",
        "spec, *, principal, arguments, grant=, pool_seeds=, unknown_arguments=, call_context=",
    ),
    "check_requested_input": _fn(
        "dispatch.check_requested_input", "spec, schema, *, pool_seeds=, call_context="
    ),
    "bind_arguments": _fn(
        "dispatch.bind_arguments",
        "spec, arguments, *, principal, target=, unknown_arguments=, call_context=, pool_seeds=",
    ),
    "resolve_target": _fn(
        "dispatch.resolve_target",
        "spec, *, principal, arguments, grant=, pool_seeds=, call_context=, seeds=",
    ),
    "present": _fn("dispatch.present", "spec, result"),
    "apresent": _fn("dispatch.apresent", "spec, result"),
    "audience_projection_for_spec": _fn(
        "dispatch.audience_projection_for_spec", "spec, *, overrides=, name="
    ),
    "present_for_audience": _fn("dispatch.present_for_audience", "spec, result, *, projection="),
    "paginate_output": _fn("dispatch.paginate_output", "rows, *, page=, limit=, max_page_size="),
    "DEFAULT_PAGE_SIZE": Pin("dispatch.paginate_output", value=100),
    "DispatchResult": Pin(
        "dispatch.dispatch_result",
        signature="kind, value=, service_result=, instance=, data=, context=",
    ),
    "authorize": _fn(
        "dispatch.authorize",
        "spec, principal, *, grant=, arguments=, call_context=, seeds=, pool_seeds=",
    ),
    "authorize_scope": _fn(
        "dispatch.authorize_scope",
        "spec, principal, scope, *, grant, arguments=, call_context=, seeds=, pool_seeds=",
    ),
    "authorize_target": _fn(
        "dispatch.authorize_target",
        "spec, principal, target, *, grant, arguments=, call_context=, seeds=, pool_seeds=",
    ),
    "Grant": Pin(
        "dispatch.grant",
        signature="spec, principal, target_checked=",
        methods={"covers": "(spec, principal)"},
    ),
    # --- adapters -----------------------------------------------------------------------------
    "filter_set_parameters": _fn("adapters.filters.filter_set_parameters", "filter_set"),
    # --- mutations ----------------------------------------------------------------------------
    "apply_input": _fn("mutations.apply_input", "instance, data, *, field_map=, exclude_fields="),
    "create_from_input": _fn(
        "mutations.create_from_input",
        "model, data, *, field_map=, exclude_fields=, m2m=, relations=, context=",
    ),
    "acreate_from_input": _fn(
        "mutations.acreate_from_input",
        "model, data, *, field_map=, exclude_fields=, m2m=, relations=, context=",
    ),
    "update_from_input": _fn(
        "mutations.update_from_input",
        "instance, data, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=, "
        "context=",
    ),
    "aupdate_from_input": _fn(
        "mutations.aupdate_from_input",
        "instance, data, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=, "
        "context=",
    ),
    "delete_relations": _fn("mutations.delete_relations", "instance, *, relations, context="),
    "adelete_relations": _fn("mutations.adelete_relations", "instance, *, relations, context="),
    # The seam the adapter fills with DRF's ValidationError from a row write.
    "register_row_error": _fn("mutations.register_row_error", "error_class, read_detail"),
    "ChangeResult": Pin(
        "mutations.change_result",
        signature="instance, created, changes, children=, relations=",
        methods={
            "changed_fields": "property",
            "get_field_change": "(field_name)",
            "get_child_change": "(relation)",
            "get_relation_change": "(relation)",
        },
    ),
    "ChildCollectionChange": Pin(
        "mutations.child_collection_change",
        signature="relation, created=, updated=, deleted=, unlinked=, removed=",
    ),
    # The adapter's own generic subclass of ChangeResult is parameterized with
    # this one, so a rename, a new bound or a second TypeVar breaks it.
    "ModelT": Pin(
        "mutations.change_result", leaf_only=True, bound=Model, parameter_of="ChangeResult"
    ),
    "FieldChange": Pin("mutations.field_change", signature="field, old, new"),
    "RelatedObjectChange": Pin(
        "mutations.related_object_change", signature="relation, outcome=, pk="
    ),
    "create_model": _fn(
        "mutations.create_model", "model, *, field_map=, exclude_fields=, m2m=, relations="
    ),
    "acreate_model": _fn(
        "mutations.acreate_model", "model, *, field_map=, exclude_fields=, m2m=, relations="
    ),
    "update_model": _fn(
        "mutations.update_model",
        "model, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=",
    ),
    "aupdate_model": _fn(
        "mutations.aupdate_model",
        "model, *, field_map=, exclude_fields=, m2m=, update_fields=, relations=",
    ),
    "delete_model": _fn("mutations.delete_model", "model, *, soft_delete=, relations="),
    "adelete_model": _fn("mutations.adelete_model", "model, *, soft_delete=, relations="),
    "delete_collection": _fn("mutations.delete_collection", "model, *, soft_delete="),
    "adelete_collection": _fn("mutations.adelete_collection", "model, *, soft_delete="),
    # --- output -------------------------------------------------------------------------------
    "Output": Pin("output.output", signature="fields=", methods={"names": "()", "get": "(name)"}),
    "OutputField": Pin(
        "output.output",
        signature="name, type, *, format=, nullable=, label=, choices=, always_present=, "
        "marking=, fields=, items=, items_nullable=, json_schema_extra=",
    ),
    # Subclassed by the adapter's serializer presenter.
    "Presenter": Pin(
        "output.presenter",
        abstract=frozenset({"output", "present"}),
        methods={"output": "()", "present": "(value)", "presented": "(value, context)"},
    ),
    # What the adapter's serializer presenter reads its serializer context from.
    "PresentationContext": Pin(
        "output.presentation_context",
        signature="principal, target=, ambient=, call_context=, shapes=",
    ),
    "FieldMarking": Pin(
        "output.field_marking",
        signature="audience=, description=, formatter=",
        methods={
            "handle": "classmethod(description=)",
            "hidden": "classmethod()",
            "label": "classmethod(description=)",
            "formatted": "classmethod(formatter, description=)",
            "timestamp": "classmethod(fmt=, description=)",
        },
    ),
    "AudienceProjection": Pin(
        "output.audience_projection",
        signature="fields=, label=, choice_labels=, nested=",
        methods={"is_empty": "()", "audience": "(name)", "formatter": "(name)"},
    ),
    "annotate_output_schema": _fn(
        "output.annotate_output_schema", "schema, projection, *, handle_description="
    ),
    "project_payload": _fn("output.project_payload", "payload, projection"),
    # --- parameters ---------------------------------------------------------------------------
    "Parameter": Pin(
        "parameters.parameters",
        signature="name, type, *, required=, format=, items=, items_nullable=, fields=, "
        "choices=, choice_labels=, minimum=, maximum=, min_length=, max_length=, default=, "
        "nullable=, help=, json_schema_extra=, reflected=",
        methods={"nested": "property"},
    ),
    "Parameters": Pin(
        "parameters.parameters",
        signature="items=",
        methods={"names": "()", "get": "(name)", "of": "classmethod(*parameters)"},
    ),
    "check_arguments": _fn(
        "parameters.check_arguments", "parameters, arguments, *, unknown_arguments=, partial="
    ),
    "coerce_flat": _fn("parameters.coerce_flat", "parameters, raw"),
    # The adapter subclasses it beside DRF's ValidationError, and reads its detail.
    "InvalidArguments": _error(
        "parameters.invalid_arguments", "detail, *, after_authorize=", "DispatchError"
    ),
    "CodedMessage": _error("parameters.coded_message", "message, code", str),
    "NON_FIELD_ERRORS": Pin("parameters.non_field_errors", value="non_field_errors"),
    # --- pool ---------------------------------------------------------------------------------
    "PoolSeeds": Pin(
        "pool.pool_seeds",
        signature="seeds=",
        methods={
            "extend": "(**seeds)",
            "names": "property",
            "reserved": "property",
            "resolvers": "()",
        },
    ),
    "DEFAULT_POOL_SEEDS": Pin("pool.pool_seeds", instance_of="PoolSeeds"),
    "RESERVED_POOL_SEEDS": Pin(
        "pool.reserved_pool_seeds",
        value=frozenset(
            {
                "user",
                "data",
                "instance",
                "collection",
                "result",
                "queryset",
                "progress",
                "call_context",
                "shapes",
            }
        ),
    ),
    "base_pool": _fn("pool.base_pool", "*, user, progress=, seeds=, **extra"),
    "combine_progress": _fn("pool.combine_progress", "*reporters"),
    "null_progress": _fn("pool.null_progress", "progress, *, total=, message=, meta="),
    "provider_keys": _fn("pool.provider_keys", "provider"),
    "resolve_callable_kwargs": _fn("pool.resolve_callable_kwargs", "fn, pool"),
    # --- registry -----------------------------------------------------------------------------
    "RegisteredSpec": Pin("registry.registered_spec", signature="name, spec, tags="),
    "SpecRegistry": Pin(
        "registry.spec_registry",
        signature="entries=",
        methods={
            "register": "(name, spec, *, tags=)",
            "get": "(name)",
            "all": "()",
            "mutations": "()",
            "queries": "()",
            "by_tag": "(*tags)",
            "subset": "(*names)",
            "merge": "(*others)",
            "specs": "()",
            "__len__": "()",
            "__contains__": "(name)",
            "__iter__": "()",
        },
    ),
    # --- relations ----------------------------------------------------------------------------
    "RelationSpec": Pin("relations.relation_spec"),
    "ChildSpec": Pin(
        "relations.child_spec",
        signature="model, fk, *, match_key=, mode=, orphan=, field_map=, exclude_fields=, m2m=, "
        "relations=, create_service=, update_service=, delete_service=",
        bases=("RelationSpec",),
    ),
    "ForwardRelationSpec": Pin(
        "relations.forward_relation_spec",
        signature="model, *, match_key=, scope=, field_map=, exclude_fields=, m2m=, relations=, "
        "create_service=, update_service=",
        bases=("RelationSpec",),
    ),
    "GenericRelationSpec": Pin(
        "relations.generic_relation_spec",
        signature="model, *, content_type_field=, object_id_field=, match_key=, mode=, orphan=, "
        "field_map=, exclude_fields=, m2m=, relations=, create_service=, update_service=, "
        "delete_service=",
        bases=("RelationSpec",),
    ),
    "ManyToManySpec": Pin(
        "relations.many_to_many_spec",
        signature="model, *, match_key=, scope=, mode=, field_map=, exclude_fields=, m2m=, "
        "relations=, create_service=, update_service=",
        bases=("RelationSpec",),
    ),
    "ReverseOneToOneSpec": Pin(
        "relations.reverse_one_to_one_spec",
        signature="model, fk, *, orphan=, field_map=, exclude_fields=, m2m=, relations=, "
        "create_service=, update_service=, delete_service=",
        bases=("RelationSpec",),
    ),
    # --- schema -------------------------------------------------------------------------------
    "can_present_nothing": _fn("schema.can_present_nothing", "spec"),
    "output_schema": _fn("schema.output_schema", "output"),
    "parameters_schema": _fn("schema.parameters_schema", "parameters, *, unknown_arguments="),
    "spec_caller_input_schema": _fn(
        "schema.spec_caller_input_schema",
        "spec, *, pool_seeds=, server_arguments=, unknown_arguments=, call_context=",
    ),
    "spec_input_schema": _fn(
        "schema.spec_input_schema", "spec, *, unknown_arguments=, call_context="
    ),
    "spec_output_schema": _fn(
        "schema.spec_output_schema", "spec, *, paginate=, projection=, handle_description="
    ),
    # --- selectors ----------------------------------------------------------------------------
    "Selector": _protocol("selectors.selector", "(*args, **kwargs)"),
    "AsyncSelector": _protocol("selectors.async_selector", "(*args, **kwargs)"),
    "ListSelector": _protocol("selectors.list_selector", "(**extras)"),
    "RetrieveSelector": _protocol("selectors.retrieve_selector", "(**extras)"),
    "run_selector": _fn("selectors.run_selector", "fn, kwargs"),
    "arun_selector": _fn("selectors.arun_selector", "fn, kwargs"),
    "materialize_retrieve": _fn("selectors.materialize_retrieve", "result"),
    "amaterialize_retrieve": _fn("selectors.amaterialize_retrieve", "result"),
    "is_queryset": _fn("selectors.is_queryset", "obj"),
    "shape_queryset": _fn("selectors.shape_queryset", "queryset, spec, pool, *, source_label"),
    # --- services -----------------------------------------------------------------------------
    "ServiceError": _error("services.service_error", "message=", Exception),
    "ServiceConflict": _error("services.service_conflict", "message=", "ServiceError"),
    "ServiceNotFound": _error("services.service_not_found", "message=", "ServiceError"),
    "ActionUnavailable": _error(
        "services.action_unavailable", "message=, *, code", "ServiceConflict"
    ),
    "AdditionalInputRequired": _error(
        "services.additional_input_required", "message, *, schema=", "ServiceError"
    ),
    "ServiceValidationError": _error("services.service_validation_error", "detail", "ServiceError"),
    "CreateService": _protocol("services.create_service", "(*, data, **extras)"),
    "UpdateService": _protocol("services.update_service", "(*, instance, data, **extras)"),
    "DeleteService": _protocol("services.delete_service", "(*, instance, data=, **extras)"),
    "implements": _fn("services.implements", "proto"),
    "run_service": _fn("services.run_service", "fn, kwargs, *, atomic"),
    "arun_service": _fn("services.arun_service", "fn, kwargs, *, atomic"),
    # --- specs --------------------------------------------------------------------------------
    # The adapter's spec classes compile to these two through the seam below.
    "ServiceSpec": Pin(
        "specs.service_spec",
        signature="*, service, permissions=, reads=, shapes=, partial=, many=, many_argument=, "
        "many_min_length=, many_max_length=, validator=, instance_selector_spec=, "
        "collection_selector_spec=, output_selector_spec=, presenter=, allow_none=, "
        "returns_many=, affordances=, atomic=, idempotent=, preconditions=, kwargs=, input_data=, "
        "progress_reporter=, metadata=",
        methods={
            "parameters": "(*, call_context=)",
            "output": "()",
            "target_selector_spec": "()",
            "presenter_for_output": "()",
        },
    ),
    "SelectorSpec": Pin(
        "specs.selector_spec",
        signature="*, kind, selector, permissions=, reads=, shapes=, presenter=, allow_none=, "
        "select_related=, prefetch_related=, annotations=, extend_queryset=, filter_set=, "
        "affordances=, kwargs=, preconditions=, progress_reporter=, metadata=",
        methods={"parameters": "(*, call_context=)", "output": "()"},
    ),
    "SpecSource": Pin("specs.spec_source", methods={"as_kernel_spec": "()"}),
    "kernel_spec": _fn("specs.kernel_spec", "spec"),
    "server_owned_keys": _fn("specs.server_owned_keys", "spec, *, pool_seeds=, call_context="),
    # --- types --------------------------------------------------------------------------------
    "DispatchError": _error("types.dispatch_error", "message=", Exception),
    "Affordance": Pin("types.affordance", signature="code, reason, when"),
    "NoInput": Pin("types.no_input"),
    "OutputPage": Pin(
        "types.output_page",
        signature="items, page, limit, total",
        methods={"total_pages": "property", "has_next": "property", "envelope": "(rendered)"},
    ),
    "ProgressReporter": _protocol(
        "types.progress_reporter", "(progress, *, total=, message=, meta=)"
    ),
    "ProviderKeys": Pin("types.provider_keys", signature="filled, declinable", bases=(tuple,)),
    "UNSET": Pin("types.unset", instance_of="UnsetType"),
    "UnsetType": Pin("types.unset"),
    "ValueFormatter": Pin(
        "types.value_formatter",
        signature="render, produces, schema=",
        methods={"apply": "(value)", "json_schema": "()", "timestamp": "classmethod(fmt=)"},
    ),
    "RelationOutcome": _enum(
        "types.relation_outcome",
        {
            "UNTOUCHED": "untouched",
            "CREATED": "created",
            "UPDATED": "updated",
            "CLEARED": "cleared",
            "UNLINKED": "unlinked",
            "DELETED": "deleted",
            "REMOVED": "removed",
        },
        str,
    ),
    "FieldAudience": _enum(
        "types.field_audience",
        {"CONTENT": "content", "LABEL": "label", "HANDLE": "handle", "HIDDEN": "hidden"},
        str,
    ),
    "RelationMode": _enum("types.relation_mode", {"REPLACE": "replace", "MERGE": "merge"}, str),
    "RelationOrphan": _enum(
        "types.relation_orphan", {"AUTO": "auto", "UNLINK": "unlink", "DELETE": "delete"}, str
    ),
    "RelationPhase": _enum(
        "types.relation_phase", {"FORWARD": 0, "REVERSE": 1, "GENERIC": 2, "M2M": 3}, int
    ),
    "is_async": _fn("types.is_async", "fn"),
    "SelectorKind": _enum("types.selector_kind", {"LIST": "list", "RETRIEVE": "retrieve"}, str),
    # The compile seam: every entry point takes an object answering as_kernel_spec().
    "UnknownArguments": _enum(
        "types.unknown_arguments",
        {"REJECT": "reject", "IGNORE": "ignore", "PASSTHROUGH": "passthrough"},
        str,
    ),
    # Subclassed by the adapter's serializer validator.
    # --- validation ---------------------------------------------------------------------------
    "Validator": Pin(
        "validation.validator",
        abstract=frozenset({"parameters", "validate"}),
        methods={
            "parameters": "()",
            "validate": "(arguments, context)",
            "validated": "(arguments, context)",
            "validated_many": "(rows, context, *, many_argument)",
        },
    ),
    "ValidationContext": Pin(
        "validation.validation_context",
        signature="principal, target=, partial=, ambient=, resolved=, call_context=",
    ),
    "Validated": Pin("validation.validated", signature="values, data, pool="),
}

# Public here and taken by nobody downstream through djangorestframework-services,
# which has its own HTTP views and its own serializer adapters. Each is a decision:
# a new root name lands in SURFACE or here, never in neither.
NOT_REEXPORTED_BY_DRFS = frozenset(
    {
        # The names dispatch reads off the call's context for a callable naming
        # one: djangorestframework-services registers ``request`` and ``view``
        # as seeds of its own, which the kernel lets stand.
        "CALL_SEEDS",
        # The report of a registry's open specs, which django-spec-cli's
        # management command and system check read from here; drfs serves no
        # management command.
        "UnguardedReason",
        "UnguardedSpec",
        "unguarded_specs",
        # Whether a spec's checks need the call's arguments to answer, which a
        # transport's filtered listing reads; drfs serves no such listing.
        "checks_read_arguments",
        # The checks asked as a call with no arguments asks them, which a
        # transport's filtered listing or OPTIONS answer asks; drfs serves
        # neither.
        "authorize_without_arguments",
        # Permission checks combined as one: a check like any other, which a
        # project's spec declares under any transport, so drfs neither wraps
        # nor re-exports them.
        "AllOf",
        "AnyOf",
        "NoneOf",
        # The seeds a prelude hands on to the call it checked, and the tuples
        # ``check_call`` and ``resolve_target`` return them on: a caller reads
        # them off those returns and never builds one, and drfs re-exports
        # none of them.
        "CallSeeds",
        "CheckedCall",
        "ResolvedTarget",
        # What mints those seeds ahead of ``authorize``, for a transport that
        # admits a call before it resolves the row: drfs authorizes through its
        # own permission classes, so it neither wraps nor re-exports it.
        "resolve_seeds",
        # The shared check that a transport's refusal map answers every kernel
        # refusal, and the findings it returns: a transport's own suite reads
        # these from the kernel, and a drfs consumer writes no refusal map.
        "REFUSALS",
        "unanswered_refusals",
        "RefusalFinding",
        "RefusalFindingKind",
        # Adapters over dataclasses and Django forms: the DRF adapter is its
        # serializer validator and presenter, which subclass Validator and
        # Presenter above instead.
        "DataclassPresenter",
        "DataclassValidator",
        "FormValidator",
        # What a FormValidator's ``form_kwargs`` returns, for a page building
        # the form itself: django-spec-html's, which drfs neither wraps nor
        # re-exports.
        "form_keywords",
        # One row's affordance answers, for a page holding raw rows rather than
        # presented dicts: djangorestframework-services neither wraps nor
        # re-exports it.
        "row_affordance_answers",
        # A transport's binding of declared parameters to server values: the
        # transports that bind call these from this package, and
        # djangorestframework-services neither wraps nor re-exports them. A
        # drfs release that starts to take them moves them into the pinned table.
        "ServerArguments",
        "check_server_arguments",
        "apply_server_arguments",
        # The readings a transport in a distribution of its own shares with the
        # kernel's, so that it refuses, relaxes and prints as they do:
        # djangorestframework-services neither wraps nor re-exports them.
        "NON_FIELD_KEYS",
        "check_permissions",
        "clean_held_to_their_columns",
        "expected_type_refusal",
        "flat_arguments",
        "is_deactivated",
        "max_length_in_force",
        "refusal_messages",
        "relax_partial",
        "sync_answer",
        # What a transport registering kernel specs reads at registration, so
        # that it refuses and relaxes what dispatch would: the transports call
        # these from this package, and djangorestframework-services neither
        # wraps nor re-exports them.
        "check_seeds",
        "provider_reached",
        "seed_named_parameters",
        "unreceived_fields",
        # How dispatch asks a Validator what it takes, for a transport asking
        # one itself during a call (django-spec-rest's rows of a ``many``
        # spec): djangorestframework-services neither wraps nor re-exports it.
        "validator_parameters",
        # A check's denial, marked so a transport can answer it with a
        # challenge: the transports that do read it from this package, and
        # djangorestframework-services neither wraps nor re-exports it.
        "PermissionCheckDenied",
        # Readers of a partial input, for a service's own code: the mutation
        # helpers already drop UNSET, and djangorestframework-services neither
        # wraps nor re-exports them.
        "is_supplied",
        "supplied_fields",
        # The call context's transport key, its reader and its builder, for a
        # transport to stamp and a stage to read: the transports use them from
        # this package, and djangorestframework-services neither wraps nor
        # re-exports them.
        "TRANSPORT_KEY",
        "build_call_context",
        "call_transport",
        # A transport's pool under its call's context: the transports use it from
        # this package, and djangorestframework-services neither wraps nor
        # re-exports it.
        "seeded_pool",
        # This package's version, which no importer reads as an API.
        "__version__",
    }
)


def _render(signature: inspect.Signature, *, bound: bool) -> str:
    """``signature`` as names, kinds and default-or-not, in Python's own notation."""
    parameters = list(signature.parameters.values())[1 if bound else 0 :]
    parts: list[str] = []
    star = False
    for index, parameter in enumerate(parameters):
        if parameter.name.startswith("_"):
            continue
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY and not star:
            parts.append("*")
            star = True
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            parts.append(f"*{parameter.name}")
            star = True
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            parts.append(f"**{parameter.name}")
        else:
            default = "=" if parameter.default is not inspect.Parameter.empty else ""
            parts.append(f"{parameter.name}{default}")
        following = parameters[index + 1].kind if index + 1 < len(parameters) else None
        if (
            parameter.kind is inspect.Parameter.POSITIONAL_ONLY
            and following is not inspect.Parameter.POSITIONAL_ONLY
        ):
            parts.append("/")
    return ", ".join(parts)


def _method(owner: type, name: str) -> str:
    """How ``owner.name`` is called: ``property``, ``classmethod(...)`` or ``(...)``."""
    attribute = inspect.getattr_static(owner, name)
    if isinstance(attribute, property):
        return "property"
    if isinstance(attribute, classmethod):
        return f"classmethod({_render(inspect.signature(getattr(owner, name)), bound=False)})"
    if isinstance(attribute, staticmethod):
        return f"staticmethod({_render(inspect.signature(getattr(owner, name)), bound=False)})"
    return f"({_render(inspect.signature(attribute), bound=True)})"


def _resolve(base: str | type) -> type:
    return getattr(django_service_specs, base) if isinstance(base, str) else base


def _rows(facet: str) -> list[str]:
    """The names whose row pins ``facet``: every row whose value differs from a bare pin's."""
    unpinned = getattr(Pin(""), facet)
    return [name for name, pin in SURFACE.items() if getattr(pin, facet) != unpinned]


# --- the table holds ----------------------------------------------------------------------------


def _leaf_value(name: str) -> Any:
    return getattr(importlib.import_module(f"{_PACKAGE}.{SURFACE[name].leaf}"), name)


@pytest.mark.parametrize("name", [name for name, pin in SURFACE.items() if not pin.leaf_only])
def test_importable_from_the_root_its_subpackage_and_its_leaf(name: str) -> None:
    leaf = SURFACE[name].leaf
    subpackage = importlib.import_module(f"{_PACKAGE}.{leaf.rpartition('.')[0]}")
    # import_module rather than attribute access.
    module = importlib.import_module(f"{_PACKAGE}.{leaf}")

    exported = getattr(django_service_specs, name)
    assert name in django_service_specs.__all__
    assert name in subpackage.__all__
    assert getattr(subpackage, name) is exported
    assert getattr(module, name) is exported


@pytest.mark.parametrize("name", _rows("leaf_only"))
def test_a_leaf_only_name_is_importable_from_its_leaf_alone(name: str) -> None:
    subpackage = importlib.import_module(f"{_PACKAGE}.{SURFACE[name].leaf.rpartition('.')[0]}")
    _leaf_value(name)
    assert name not in django_service_specs.__all__
    assert name not in subpackage.__all__


@pytest.mark.parametrize("name", _rows("bound"))
def test_a_type_variable_as_pinned(name: str) -> None:
    pin = SURFACE[name]
    type_var = _leaf_value(name)
    assert isinstance(type_var, TypeVar)
    assert type_var.__name__ == name
    assert type_var.__bound__ is pin.bound
    assert pin.parameter_of is not None
    assert getattr(django_service_specs, pin.parameter_of).__parameters__ == (type_var,)


@pytest.mark.parametrize("name", _rows("signature"))
def test_called_as_pinned(name: str) -> None:
    exported = getattr(django_service_specs, name)
    assert _render(inspect.signature(exported), bound=False) == SURFACE[name].signature


@pytest.mark.parametrize("name", _rows("methods"))
def test_methods_called_as_pinned(name: str) -> None:
    owner = getattr(django_service_specs, name)
    pinned = SURFACE[name].methods
    assert {method: _method(owner, method) for method in pinned} == dict(pinned)


@pytest.mark.parametrize("name", _rows("abstract"))
def test_a_subclass_owes_only_the_pinned_abstract_methods(name: str) -> None:
    # A new abstract method breaks every subclass downstream at instantiation.
    assert getattr(django_service_specs, name).__abstractmethods__ == SURFACE[name].abstract


@pytest.mark.parametrize("name", _rows("bases"))
def test_keeps_its_pinned_bases(name: str) -> None:
    # An exception ladder catching the base.
    exported = getattr(django_service_specs, name)
    for base in SURFACE[name].bases:
        assert issubclass(exported, _resolve(base)), base


@pytest.mark.parametrize("name", _rows("members"))
def test_enum_members_as_pinned(name: str) -> None:
    exported = getattr(django_service_specs, name)
    assert issubclass(exported, enum.Enum)
    # Iteration skips an alias, so a member redefined as another's value fails.
    assert {member.name: member.value for member in exported} == dict(SURFACE[name].members or {})


@pytest.mark.parametrize("name", _rows("value"))
def test_constant_value_as_pinned(name: str) -> None:
    assert getattr(django_service_specs, name) == SURFACE[name].value


@pytest.mark.parametrize("name", _rows("instance_of"))
def test_value_of_the_pinned_type(name: str) -> None:
    pinned = SURFACE[name].instance_of
    assert pinned is not None
    assert isinstance(getattr(django_service_specs, name), _resolve(pinned))


@pytest.mark.parametrize(
    ("name", "args", "kwargs", "attributes"),
    [
        ("DispatchError", (), {}, {"message", "default_message"}),
        ("NotPermitted", (), {}, {"message", "default_message"}),
        ("PrincipalUnavailable", (), {}, {"message", "default_message"}),
        ("InvalidArguments", ({"title": ["Required."]},), {}, {"detail", "message"}),
        ("ServiceError", (), {}, {"message", "default_message"}),
        ("ServiceConflict", (), {}, {"message", "default_message"}),
        ("ServiceNotFound", (), {}, {"message", "default_message"}),
        ("ActionUnavailable", (), {"code": "closed"}, {"message", "code"}),
        ("AdditionalInputRequired", ("Confirm?",), {"schema": {}}, {"message", "schema"}),
        ("ServiceValidationError", ({"title": ["Taken."]},), {}, {"detail", "message"}),
    ],
)
def test_exceptions_carry_what_a_translator_reads(
    name: str, args: tuple[Any, ...], kwargs: dict[str, Any], attributes: set[str]
) -> None:
    # A translator re-raising these as DRF's exceptions, and a transport's exception ladder.
    raised = getattr(django_service_specs, name)(*args, **kwargs)
    assert {attribute for attribute in attributes if hasattr(raised, attribute)} == attributes


# --- the table is complete ----------------------------------------------------------------------


def test_every_root_name_is_pinned_or_named_as_not_taken() -> None:
    exported = set(django_service_specs.__all__)
    assert exported - set(SURFACE) - NOT_REEXPORTED_BY_DRFS == set()


def test_no_name_is_both_pinned_and_named_as_not_taken() -> None:
    assert set(SURFACE) & NOT_REEXPORTED_BY_DRFS == set()


def test_every_name_held_out_is_still_public() -> None:
    # A stale entry would let a later name of the same spelling through unpinned.
    assert NOT_REEXPORTED_BY_DRFS - set(django_service_specs.__all__) == set()


# --- the rendering the pins are read through ----------------------------------------------------


def _positional_only(a: int, /, b: int) -> None: ...


def _everything(a: int, b: int = 0, *args: int, c: int, d: int = 0, **kwargs: int) -> None: ...


def _keyword_only(*, a: int) -> None: ...


def _private_tail(a: int, *, _hidden: int = 0) -> None: ...


@pytest.mark.parametrize(
    ("function", "rendered"),
    [
        (_positional_only, "a, /, b"),
        (_everything, "a, b=, *args, c, d=, **kwargs"),
        (_keyword_only, "*, a"),
        (_private_tail, "a"),
    ],
)
def test_the_rendering_tells_every_kind_apart(function: Any, rendered: str) -> None:
    # The pins are only as strict as this rendering: a parameter made keyword-only.
    assert _render(inspect.signature(function), bound=False) == rendered


def test_the_rendering_tells_method_kinds_apart() -> None:
    class Owner:
        def method(self, a: int) -> None: ...

        @classmethod
        def made(cls, a: int) -> None: ...

        @staticmethod
        def plain(a: int) -> None: ...

        @property
        def value(self) -> int:
            return 0

    assert [_method(Owner, name) for name in ("method", "made", "plain", "value")] == [
        "(a)",
        "classmethod(a)",
        "staticmethod(a)",
        "property",
    ]


# --- an open selector spec to dispatch --------------------------------------------------


def _open_selector(selector: Any = None) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=selector if selector is not None else _no_rows,
        permissions=[Unrestricted()],
    )


def _no_rows() -> list[Any]:
    return []


# --- UnknownArguments.PASSTHROUGH ---------------------------------------------------------------
#
# The published MCP transport tests ``unknown_arguments is
# UnknownArguments.PASSTHROUGH`` on a policy it was configured with. The member
# keeps that line evaluating to False for IGNORE, where a missing member would
# raise AttributeError; as a policy it is refused everywhere one is read.

_REFUSED = r"UnknownArguments\.PASSTHROUGH is refused"


def test_passthrough_is_a_member_of_its_own() -> None:
    passthrough = UnknownArguments.PASSTHROUGH
    assert passthrough.value == "passthrough"
    assert UnknownArguments("passthrough") is passthrough
    # An alias of IGNORE would make the transport's test true and change which branch it takes.
    assert passthrough in list(UnknownArguments)
    configured = UnknownArguments.IGNORE
    assert (configured is UnknownArguments.PASSTHROUGH) is False


def test_dispatch_refuses_passthrough_rather_than_running_it_as_ignore() -> None:
    calls: list[int] = []

    def notes() -> list[Any]:
        calls.append(1)
        return []

    spec = _open_selector(notes)
    # Sized so the policy answers: an anonymous principal no deactivation check refuses.
    dispatch(
        spec,
        principal=AnonymousUser(),
        arguments={"tenant": "acme"},
        unknown_arguments=UnknownArguments.IGNORE,
    )
    assert calls == [1]

    with pytest.raises(ValueError, match=_REFUSED):
        dispatch(
            spec,
            principal=AnonymousUser(),
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )
    assert calls == [1]


async def test_adispatch_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        await adispatch(
            _open_selector(),
            principal=AnonymousUser(),
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )


def test_check_call_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        check_call(
            _open_selector(),
            principal=AnonymousUser(),
            arguments={"tenant": "acme"},
            unknown_arguments=UnknownArguments.PASSTHROUGH,
        )


def test_check_arguments_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        check_arguments(
            Parameters(), {"tenant": "acme"}, unknown_arguments=UnknownArguments.PASSTHROUGH
        )


def test_parameters_schema_refuses_passthrough() -> None:
    with pytest.raises(ValueError, match=_REFUSED):
        parameters_schema(Parameters(), unknown_arguments=UnknownArguments.PASSTHROUGH)
