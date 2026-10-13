"""``Validated`` - what one call's validation hands the operation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Validated:
    """The values a call's service is called with, its ``data``, and what else it binds.

    [`Validator.validated()`][django_service_specs.validation.validator.Validator.validated]
    returns one, and dispatch builds the call's pool from it: ``values``
    spread by name, ``data`` under its own name, and ``pool`` beside both.

    - ``values`` is what ``validate()`` returns: the validated values keyed by
      the name the service takes each under.
    - ``data`` is the validated object as a whole, which a service declaring
      ``data`` receives. For a mapping Validator it is ``values`` itself; for
      [`DataclassValidator`][django_service_specs.adapters.dataclass.dataclass_validator.DataclassValidator]
      it is the instance, whose fields ``values`` holds.
    - ``pool`` is any other value the Validator binds for this one call, such
      as the bound object a library validated through, so a service can ask
      for it by name. Empty unless the Validator says otherwise.

    Three fields rather than one mapping, because ``data`` need not be a
    mapping at all, and a value bound for the call is not one the caller sent:
    neither belongs among the values a caller's argument names.
    """

    values: dict[str, Any]
    data: Any
    pool: Mapping[str, Any] = field(default_factory=dict)
