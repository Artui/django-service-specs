# API reference

Everything below is exported from `django_service_specs` directly, and from the
subpackage it is listed under. Import from the package root in application
code; the subpackage paths are where each name is defined.

The pydantic adapters are the one exception. pydantic is an optional extra,
so they are exported from `django_service_specs.adapters.pydantic` alone, and
importing the package root never imports pydantic.

## Specs

::: django_service_specs.specs.service_spec.ServiceSpec
::: django_service_specs.specs.selector_spec.SelectorSpec
::: django_service_specs.specs.selector_kind.SelectorKind

## Parameters

::: django_service_specs.parameters.parameter.Parameter
::: django_service_specs.parameters.parameters.Parameters
::: django_service_specs.parameters.check_arguments.check_arguments
::: django_service_specs.parameters.coerce_flat.coerce_flat
::: django_service_specs.parameters.invalid_arguments.InvalidArguments

## Validation

::: django_service_specs.validation.validator.Validator
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
::: django_service_specs.dispatch.paginate_output.paginate_output
::: django_service_specs.dispatch.paginate_output.DEFAULT_PAGE_SIZE
::: django_service_specs.dispatch.bind_arguments.bind_arguments

## Affordances

::: django_service_specs.affordances.enforce_affordances.enforce_affordances
::: django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance
::: django_service_specs.affordances.operation_affordances.operation_affordances

## HTTP

::: django_service_specs.http.dispatch_request.dispatch_request
::: django_service_specs.http.adispatch_request.adispatch_request
::: django_service_specs.http.spec_view.SpecView
::: django_service_specs.http.async_spec_view.AsyncSpecView
::: django_service_specs.http.spec_form_view.SpecFormView
::: django_service_specs.http.request_arguments.request_arguments
::: django_service_specs.http.error_response.error_response
::: django_service_specs.http.unsupported_media_type.UnsupportedMediaType
::: django_service_specs.http.add_argument_errors.add_argument_errors

## Authorization

::: django_service_specs.authorization.permission_check.PermissionCheck
::: django_service_specs.authorization.unrestricted.Unrestricted
::: django_service_specs.authorization.grant.Grant
::: django_service_specs.authorization.authorize.authorize
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

## Pool

::: django_service_specs.pool.pool_seeds.PoolSeeds
::: django_service_specs.pool.pool_seeds.DEFAULT_POOL_SEEDS
::: django_service_specs.pool.reserved_pool_seeds.RESERVED_POOL_SEEDS
::: django_service_specs.pool.base_pool.base_pool
::: django_service_specs.pool.null_progress.null_progress
::: django_service_specs.pool.resolve_callable_kwargs.resolve_callable_kwargs

## Mutations

::: django_service_specs.mutations.create_from_input.create_from_input
::: django_service_specs.mutations.acreate_from_input.acreate_from_input
::: django_service_specs.mutations.update_from_input.update_from_input
::: django_service_specs.mutations.aupdate_from_input.aupdate_from_input
::: django_service_specs.mutations.apply_input.apply_input
::: django_service_specs.mutations.delete_relations.delete_relations
::: django_service_specs.mutations.adelete_relations.adelete_relations
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

## Types

::: django_service_specs.types.dispatch_error.DispatchError
::: django_service_specs.types.unset.UNSET
::: django_service_specs.types.unset.UnsetType
::: django_service_specs.types.affordance.Affordance
::: django_service_specs.types.progress_reporter.ProgressReporter
::: django_service_specs.types.output_page.OutputPage
