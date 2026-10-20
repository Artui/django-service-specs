"""``REFUSALS`` - every refusal the kernel raises, for a transport's map to answer."""

from __future__ import annotations

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.additional_input_required import AdditionalInputRequired
from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.types.dispatch_error import DispatchError

REFUSALS: tuple[type[DispatchError] | type[ServiceError], ...] = (
    DispatchError,
    InvalidArguments,
    NotPermitted,
    PrincipalUnavailable,
    ServiceError,
    ServiceNotFound,
    ServiceConflict,
    ActionUnavailable,
    AdditionalInputRequired,
    ServiceValidationError,
)
"""Every refusal the kernel defines, family by family, each base before what is under it.

Two families: a [`DispatchError`][django_service_specs.types.dispatch_error.DispatchError]
refuses the call before the operation runs, and a
[`ServiceError`][django_service_specs.services.service_error.ServiceError] is the
operation's own refusal. Both bases are listed, because either may be raised
bare, and so is ``ServiceConflict``, the base of ``ActionUnavailable``.

A refusal a transport defines - ``http/``'s ``UnsupportedMediaType`` is one -
is not here: that transport maps it and tests it. Read by
[`unanswered_refusals`][django_service_specs.dispatch.unanswered_refusals.unanswered_refusals];
a test walking the class tree holds it equal to the package's own refusals,
so one a later release adds fails there until it is listed."""
