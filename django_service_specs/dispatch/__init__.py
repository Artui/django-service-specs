"""Running one operation, from any transport."""

from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.dispatch_result import DispatchResult

__all__ = ["DispatchResult", "bind_arguments"]
