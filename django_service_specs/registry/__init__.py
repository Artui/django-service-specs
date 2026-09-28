"""A named home for a project's spec set.

Declare each operation once; every transport reads the same source instead of
enumerating the specs again and drifting. Behavioural (a registry holds
state), so it lives here rather than in ``types/`` - where its value type,
``RegisteredSpec``, does.
"""

from django_service_specs.registry.registered_spec import RegisteredSpec
from django_service_specs.registry.spec_registry import SpecRegistry

__all__ = ["RegisteredSpec", "SpecRegistry"]
