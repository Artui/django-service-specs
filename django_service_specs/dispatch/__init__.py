"""Running one operation, from any transport, and the authorization checks it runs."""

from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.check_requested_input import check_requested_input
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.paginate_output import DEFAULT_PAGE_SIZE, paginate_output
from django_service_specs.dispatch.present import present
from django_service_specs.dispatch.present_for_audience import present_for_audience
from django_service_specs.dispatch.resolve_target import resolve_target

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "DispatchResult",
    "Grant",
    "adispatch",
    "apresent",
    "audience_projection_for_spec",
    "authorize",
    "authorize_scope",
    "authorize_target",
    "bind_arguments",
    "check_call",
    "check_requested_input",
    "dispatch",
    "paginate_output",
    "present",
    "present_for_audience",
    "resolve_target",
]
