# API reference

Everything below is exported from `django_service_specs` directly, and from the
subpackage it is listed under. Import from the package root in application
code; the subpackage paths are where each name is defined.

The pydantic adapters are the one exception. pydantic is an optional extra,
so they are exported from `django_service_specs.adapters.pydantic` alone, and
importing the package root never imports pydantic.

## Settings

One Django setting, read at the call rather than at import, so
`override_settings` reaches a spec built before it. The management command's
output format is `SPEC_CLI_OUTPUT`, read by
[django-spec-cli](https://artui.github.io/django-spec-cli/).

- **`SERVICE_SPECS_MAX_ARRAY_LENGTH`**: the most elements an array argument
  takes where its parameter declares no `max_length`, and the most rows a
  `many` call carries where its spec declares no `many_max_length`. `1000`
  when unset; `None` bounds no array. Anything but a non-negative `int` or
  `None` is refused as `ImproperlyConfigured` where it is read. See
  [how long a list may be](arguments.md#how-long-a-list-may-be).
  [django-spec-html](https://artui.github.io/django-spec-html/)'s request
  reader bounds a query string's lists by the same key.

## Specs

::: django_service_specs.specs.service_spec.ServiceSpec
::: django_service_specs.specs.selector_spec.SelectorSpec
::: django_service_specs.specs.spec_source.SpecSource
::: django_service_specs.specs.kernel_spec.kernel_spec

## Parameters

::: django_service_specs.parameters.parameters.Parameter
::: django_service_specs.parameters.parameters.Parameters
::: django_service_specs.parameters.check_arguments.check_arguments
::: django_service_specs.parameters.non_field_errors.NON_FIELD_ERRORS
::: django_service_specs.parameters.non_field_keys.NON_FIELD_KEYS
::: django_service_specs.parameters.coerce_flat.coerce_flat
::: django_service_specs.parameters.invalid_arguments.InvalidArguments
::: django_service_specs.parameters.coded_message.CodedMessage
::: django_service_specs.parameters.refusal_messages.refusal_messages
::: django_service_specs.parameters.expected_type_refusal.expected_type_refusal
::: django_service_specs.parameters.max_length_in_force.max_length_in_force
::: django_service_specs.parameters.clean_held_to_their_columns.clean_held_to_their_columns

## Validation

::: django_service_specs.validation.validator.Validator
::: django_service_specs.validation.validated.Validated

::: django_service_specs.validation.validation_context.ValidationContext

## Output

::: django_service_specs.output.presenter.Presenter
::: django_service_specs.output.presentation_context.PresentationContext
::: django_service_specs.output.output.Output
::: django_service_specs.output.output.OutputField
::: django_service_specs.output.field_marking.FieldMarking
::: django_service_specs.output.audience_projection.AudienceProjection
::: django_service_specs.dispatch.audience_projection_for_spec.audience_projection_for_spec
::: django_service_specs.output.project_payload.project_payload
::: django_service_specs.output.annotate_output_schema.annotate_output_schema

## JSON Schema

::: django_service_specs.schema.spec_input_schema.spec_input_schema
::: django_service_specs.schema.spec_output_schema.spec_output_schema
::: django_service_specs.schema.parameters_schema.parameters_schema
::: django_service_specs.schema.output_schema.output_schema
::: django_service_specs.schema.can_present_nothing.can_present_nothing

## Dataclass adapters

::: django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator
::: django_service_specs.adapters.dataclass.dataclass_presenter.DataclassPresenter

## Forms adapter

::: django_service_specs.adapters.forms.form_validator.FormValidator
::: django_service_specs.adapters.forms.form_keywords.form_keywords

## Filters adapter

::: django_service_specs.adapters.filters.filter_set_parameters.filter_set_parameters

## Pydantic adapters

Installed with the `pydantic` extra and imported from
`django_service_specs.adapters.pydantic`.

::: django_service_specs.adapters.pydantic.pydantic_validator.PydanticValidator
::: django_service_specs.adapters.pydantic.pydantic_presenter.PydanticPresenter

## Dispatch

::: django_service_specs.dispatch.dispatch.dispatch
::: django_service_specs.dispatch.adispatch.adispatch
::: django_service_specs.dispatch.dispatch_result.DispatchResult
::: django_service_specs.dispatch.present.present
::: django_service_specs.dispatch.apresent.apresent
::: django_service_specs.dispatch.present_for_audience.present_for_audience
::: django_service_specs.dispatch.resolve_target.resolve_target
::: django_service_specs.dispatch.paginate_output.paginate_output
::: django_service_specs.dispatch.paginate_output.DEFAULT_PAGE_SIZE
::: django_service_specs.dispatch.bind_arguments.bind_arguments
::: django_service_specs.dispatch.check_requested_input.check_requested_input
::: django_service_specs.dispatch.check_call.check_call
::: django_service_specs.dispatch.check_seeds.check_seeds
::: django_service_specs.dispatch.seed_named_parameters.seed_named_parameters
::: django_service_specs.dispatch.provider_reached.provider_reached
::: django_service_specs.dispatch.unreceived_fields.unreceived_fields
::: django_service_specs.dispatch.check_server_arguments.check_server_arguments
::: django_service_specs.dispatch.apply_server_arguments.apply_server_arguments
::: django_service_specs.dispatch.refusals.REFUSALS
::: django_service_specs.dispatch.unanswered_refusals.unanswered_refusals
::: django_service_specs.dispatch.relax_partial.relax_partial

## Affordances

::: django_service_specs.affordances.enforce_affordances.enforce_affordances
::: django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance
::: django_service_specs.affordances.operation_affordances.operation_affordances
::: django_service_specs.affordances.aenforce_affordances.aenforce_affordances
::: django_service_specs.affordances.aunmet_operation_affordance.aunmet_operation_affordance
::: django_service_specs.affordances.row_affordance_answers.row_affordance_answers

## Authorization

::: django_service_specs.authorization.permission_check.PermissionCheck
::: django_service_specs.authorization.unrestricted.Unrestricted
::: django_service_specs.dispatch.grant.Grant
::: django_service_specs.dispatch.authorize.authorize
::: django_service_specs.dispatch.authorize_scope.authorize_scope
::: django_service_specs.dispatch.checks_read_arguments.checks_read_arguments
::: django_service_specs.dispatch.authorize_target.authorize_target
::: django_service_specs.authorization.resolve_principal.resolve_principal
::: django_service_specs.authorization.is_deactivated.is_deactivated
::: django_service_specs.authorization.not_permitted.NotPermitted
::: django_service_specs.authorization.principal_unavailable.PrincipalUnavailable

## Services

::: django_service_specs.services.run_service.run_service
::: django_service_specs.services.arun_service.arun_service
::: django_service_specs.services.service_error.ServiceError
::: django_service_specs.services.service_validation_error.ServiceValidationError
::: django_service_specs.services.service_conflict.ServiceConflict
::: django_service_specs.services.service_not_found.ServiceNotFound
::: django_service_specs.services.action_unavailable.ActionUnavailable
::: django_service_specs.services.additional_input_required.AdditionalInputRequired
::: django_service_specs.services.create_service.CreateService
::: django_service_specs.services.update_service.UpdateService
::: django_service_specs.services.delete_service.DeleteService
::: django_service_specs.services.implements.implements

## Pool

::: django_service_specs.pool.pool_seeds.PoolSeeds
::: django_service_specs.pool.pool_seeds.DEFAULT_POOL_SEEDS
::: django_service_specs.pool.reserved_pool_seeds.RESERVED_POOL_SEEDS
::: django_service_specs.pool.call_seeds.CALL_SEEDS
::: django_service_specs.pool.base_pool.base_pool
::: django_service_specs.pool.null_progress.null_progress
::: django_service_specs.pool.combine_progress.combine_progress
::: django_service_specs.pool.provider_keys.provider_keys
::: django_service_specs.specs.server_owned_keys.server_owned_keys
::: django_service_specs.pool.resolve_callable_kwargs.resolve_callable_kwargs

## Mutations

::: django_service_specs.mutations.create_from_input.create_from_input
::: django_service_specs.mutations.acreate_from_input.acreate_from_input
::: django_service_specs.mutations.update_from_input.update_from_input
::: django_service_specs.mutations.aupdate_from_input.aupdate_from_input
::: django_service_specs.mutations.apply_input.apply_input
::: django_service_specs.mutations.delete_relations.delete_relations
::: django_service_specs.mutations.adelete_relations.adelete_relations
::: django_service_specs.mutations.register_row_error.register_row_error
::: django_service_specs.mutations.change_result.ChangeResult
::: django_service_specs.mutations.field_change.FieldChange
::: django_service_specs.mutations.child_collection_change.ChildCollectionChange
::: django_service_specs.mutations.related_object_change.RelatedObjectChange
::: django_service_specs.mutations.create_model.create_model
::: django_service_specs.mutations.acreate_model.acreate_model
::: django_service_specs.mutations.update_model.update_model
::: django_service_specs.mutations.aupdate_model.aupdate_model
::: django_service_specs.mutations.delete_model.delete_model
::: django_service_specs.mutations.adelete_model.adelete_model
::: django_service_specs.mutations.delete_collection.delete_collection
::: django_service_specs.mutations.adelete_collection.adelete_collection

## Relations

::: django_service_specs.relations.relation_spec.RelationSpec
::: django_service_specs.relations.child_spec.ChildSpec
::: django_service_specs.relations.forward_relation_spec.ForwardRelationSpec
::: django_service_specs.relations.reverse_one_to_one_spec.ReverseOneToOneSpec
::: django_service_specs.relations.many_to_many_spec.ManyToManySpec
::: django_service_specs.relations.generic_relation_spec.GenericRelationSpec

## Registry

::: django_service_specs.registry.spec_registry.SpecRegistry
::: django_service_specs.registry.registered_spec.RegisteredSpec
::: django_service_specs.registry.unguarded_specs.unguarded_specs
::: django_service_specs.registry.unguarded_spec.UnguardedSpec

## Selectors

::: django_service_specs.selectors.shape_queryset.shape_queryset
::: django_service_specs.selectors.run_selector.run_selector
::: django_service_specs.selectors.arun_selector.arun_selector
::: django_service_specs.selectors.materialize_retrieve.materialize_retrieve
::: django_service_specs.selectors.amaterialize_retrieve.amaterialize_retrieve
::: django_service_specs.selectors.is_queryset.is_queryset
::: django_service_specs.selectors.selector.Selector
::: django_service_specs.selectors.async_selector.AsyncSelector
::: django_service_specs.selectors.list_selector.ListSelector
::: django_service_specs.selectors.retrieve_selector.RetrieveSelector

## Types

::: django_service_specs.types.dispatch_error.DispatchError
::: django_service_specs.types.unset.UNSET
::: django_service_specs.types.unset.UnsetType
::: django_service_specs.types.affordance.Affordance
::: django_service_specs.types.progress_reporter.ProgressReporter
::: django_service_specs.types.provider_keys.ProviderKeys
::: django_service_specs.types.server_arguments.ServerArguments
::: django_service_specs.types.output_page.OutputPage
::: django_service_specs.types.value_formatter.ValueFormatter
::: django_service_specs.types.no_input.NoInput
::: django_service_specs.types.unguarded_reason.UnguardedReason
::: django_service_specs.types.refusal_finding.RefusalFinding
::: django_service_specs.types.refusal_finding_kind.RefusalFindingKind
::: django_service_specs.types.selector_kind.SelectorKind
::: django_service_specs.types.field_audience.FieldAudience
::: django_service_specs.types.unknown_arguments.UnknownArguments
::: django_service_specs.types.relation_mode.RelationMode
::: django_service_specs.types.relation_orphan.RelationOrphan
::: django_service_specs.types.relation_phase.RelationPhase
::: django_service_specs.types.relation_outcome.RelationOutcome
::: django_service_specs.types.is_async.is_async
