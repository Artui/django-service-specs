"""Who is acting, and whether they may."""

from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.authorize_target import authorize_target
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.resolve_principal import resolve_principal
from django_service_specs.authorization.unrestricted import Unrestricted

__all__ = [
    "Grant",
    "NotPermitted",
    "PermissionCheck",
    "PrincipalUnavailable",
    "Unrestricted",
    "authorize",
    "authorize_target",
    "resolve_principal",
]
