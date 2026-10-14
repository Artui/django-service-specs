# API reference

Everything below is exported from `django_service_specs` directly, and from the
subpackage it is listed under. Import from the package root in application
code; the subpackage paths are where each name is defined.

The pydantic adapters are the one exception. pydantic is an optional extra,
so they are exported from `django_service_specs.adapters.pydantic` alone, and
importing the package root never imports pydantic.

## Settings

Two Django settings, each read at the call rather than at import, so
`override_settings` reaches a spec built before it.

- **`SERVICE_SPECS_MAX_ARRAY_LENGTH`**: the most elements an array argument
  takes where its parameter declares no `max_length`, and the most rows a
  `many` call carries where its spec declares no `many_max_length`. `1000`
  when unset; `None` bounds no array. Anything but a non-negative `int` or
  `None` is refused as `ImproperlyConfigured` where it is read. See
  [how long a list may be](arguments.md#how-long-a-list-may-be).
- **`SERVICE_SPECS_COMMAND_OUTPUT`**: the format a `SpecCommand` writes its
  result in. `"auto"` when unset, a table on a terminal and JSON Lines on
  anything else; `"table"` or `"json"` pins one project-wide, and a
  command's own `--table` or `--json` still wins. Anything else, a
  different case included, is refused as `ImproperlyConfigured` where it is
  read. See [`wants_table`][django_service_specs.commands.wants_table.wants_table].

## Specs

::: django_service_specs.specs.service_spec.ServiceSpec
::: django_service_specs.specs.selector_spec.SelectorSpec
::: django_service_specs.specs.selector_kind.SelectorKind
::: django_service_specs.specs.spec_source.SpecSource
::: django_service_specs.specs.kernel_spec.kernel_spec

## Parameters

::: django_service_specs.parameters.parameter.Parameter
::: django_service_specs.parameters.parameters.Parameters
::: django_service_specs.parameters.check_arguments.check_arguments
::: django_service_specs.parameters.non_field_errors.NON_FIELD_ERRORS
::: django_service_specs.parameters.coerce_flat.coerce_flat
::: django_service_specs.parameters.invalid_arguments.InvalidArguments
::: django_service_specs.parameters.coded_message.CodedMessage

## Validation

::: django_service_specs.validation.validator.Validator
::: django_service_specs.validation.validated.Validated

::: django_service_specs.validation.validation_context.ValidationContext
::: django_service_specs.validation.unknown_arguments.UnknownArguments

## Output

::: django_service_specs.output.presenter.Presenter
::: django_service_specs.output.output.Output
::: django_service_specs.output.output_field.OutputField
::: django_service_specs.output.field_marking.FieldMarking
::: django_service_specs.output.field_audience.FieldAudience
::: django_service_specs.output.audience_projection.AudienceProjection
::: django_service_specs.output.audience_projection_for_spec.audience_projection_for_spec
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

## Affordances

::: django_service_specs.affordances.enforce_affordances.enforce_affordances
::: django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance
::: django_service_specs.affordances.operation_affordances.operation_affordances
::: django_service_specs.affordances.aenforce_affordances.aenforce_affordances
::: django_service_specs.affordances.aunmet_operation_affordance.aunmet_operation_affordance

## HTTP

::: django_service_specs.http.dispatch_request.dispatch_request
::: django_service_specs.http.adispatch_request.adispatch_request
::: django_service_specs.http.spec_view.SpecView
::: django_service_specs.http.async_spec_view.AsyncSpecView
::: django_service_specs.http.request_arguments.request_arguments
::: django_service_specs.http.request_principal.request_principal
::: django_service_specs.http.route_arguments.route_arguments
::: django_service_specs.http.error_response.error_response
::: django_service_specs.http.unsupported_media_type.UnsupportedMediaType
::: django_service_specs.http.add_argument_errors.add_argument_errors

## Authorization

::: django_service_specs.authorization.permission_check.PermissionCheck
::: django_service_specs.authorization.unrestricted.Unrestricted
::: django_service_specs.authorization.grant.Grant
::: django_service_specs.authorization.authorize.authorize
::: django_service_specs.authorization.authorize_scope.authorize_scope
::: django_service_specs.authorization.authorize_target.authorize_target
::: django_service_specs.authorization.resolve_principal.resolve_principal
::: django_service_specs.authorization.not_permitted.NotPermitted
::: django_service_specs.authorization.principal_unavailable.PrincipalUnavailable

## Services

::: django_service_specs.services.run_service.run_service
::: django_service_specs.services.arun_service.arun_service
::: django_service_specs.services.is_async.is_async
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
::: django_service_specs.services.create_model.create_model
::: django_service_specs.services.acreate_model.acreate_model
::: django_service_specs.services.update_model.update_model
::: django_service_specs.services.aupdate_model.aupdate_model
::: django_service_specs.services.delete_model.delete_model
::: django_service_specs.services.adelete_model.adelete_model
::: django_service_specs.services.delete_collection.delete_collection
::: django_service_specs.services.adelete_collection.adelete_collection

## Pool

::: django_service_specs.pool.pool_seeds.PoolSeeds
::: django_service_specs.pool.pool_seeds.DEFAULT_POOL_SEEDS
::: django_service_specs.pool.reserved_pool_seeds.RESERVED_POOL_SEEDS
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
::: django_service_specs.mutations.relation_outcome.RelationOutcome

## Relations

::: django_service_specs.relations.relation_spec.RelationSpec
::: django_service_specs.relations.child_spec.ChildSpec
::: django_service_specs.relations.forward_relation_spec.ForwardRelationSpec
::: django_service_specs.relations.reverse_one_to_one_spec.ReverseOneToOneSpec
::: django_service_specs.relations.many_to_many_spec.ManyToManySpec
::: django_service_specs.relations.generic_relation_spec.GenericRelationSpec
::: django_service_specs.relations.relation_mode.RelationMode
::: django_service_specs.relations.relation_orphan.RelationOrphan
::: django_service_specs.relations.relation_phase.RelationPhase

## Registry

::: django_service_specs.registry.spec_registry.SpecRegistry
::: django_service_specs.registry.registered_spec.RegisteredSpec

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

## Commands

::: django_service_specs.commands.spec_command.SpecCommand
::: django_service_specs.commands.exit_code_for.exit_code_for
::: django_service_specs.commands.render_result.render_result
::: django_service_specs.commands.render_table.render_table
::: django_service_specs.commands.render_json_lines.render_json_lines
::: django_service_specs.commands.wants_table.wants_table
::: django_service_specs.commands.argv.describe_parameters.describe_parameters
::: django_service_specs.commands.argv.parameter_descriptor.ParameterDescriptor
::: django_service_specs.commands.argv.add_spec_arguments.add_spec_arguments
::: django_service_specs.commands.argv.parsed_arguments.parsed_arguments
::: django_service_specs.commands.unguarded_specs.unguarded_specs
::: django_service_specs.commands.unguarded_spec.UnguardedSpec
::: django_service_specs.commands.unguarded_message.unguarded_message

## Filters

::: django_service_specs.filters.filter_set_parameters.filter_set_parameters

## Types

::: django_service_specs.types.dispatch_error.DispatchError
::: django_service_specs.types.unset.UNSET
::: django_service_specs.types.unset.UnsetType
::: django_service_specs.types.affordance.Affordance
::: django_service_specs.types.progress_reporter.ProgressReporter
::: django_service_specs.types.provider_keys.ProviderKeys
::: django_service_specs.types.output_page.OutputPage
::: django_service_specs.types.value_formatter.ValueFormatter
::: django_service_specs.types.no_input.NoInput
::: django_service_specs.types.exit_code.ExitCode
::: django_service_specs.types.unguarded_reason.UnguardedReason
