"""Running one operation, from any transport."""

from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.paginate_output import DEFAULT_PAGE_SIZE, paginate_output
from django_service_specs.dispatch.present import present
from django_service_specs.dispatch.present_for_audience import present_for_audience

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "DispatchResult",
    "adispatch",
    "apresent",
    "bind_arguments",
    "dispatch",
    "paginate_output",
    "present",
    "present_for_audience",
]
