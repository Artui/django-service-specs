"""Who is acting, what decides whether they may, and the refusals when they may not."""

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.resolve_principal import resolve_principal
from django_service_specs.authorization.unrestricted import Unrestricted

__all__ = [
    "NotPermitted",
    "PermissionCheck",
    "PrincipalUnavailable",
    "Unrestricted",
    "resolve_principal",
]
