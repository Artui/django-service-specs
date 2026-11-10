from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django import forms
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.utils import pool_kwargs
from django_service_specs.types.utils import CALL_CONTEXT
from django_service_specs.validation.validation_context import ValidationContext

BOUND_KEYWORDS = frozenset({"data", "files", "instance"})
"""The constructor keywords the bind sets itself, which ``form_kwargs`` may not
return: ``instance`` too for a plain form, so a callable's keywords mean one
thing whichever kind of form it serves."""


def extra_keywords(
    form_class: type[forms.BaseForm],
    form_kwargs: Callable[..., Mapping[str, Any]] | None,
    context: ValidationContext,
) -> Mapping[str, Any]:
    """What ``form_kwargs`` returns for this call, or nothing when there is none."""
    if form_kwargs is None:
        return {}
    pool = {
        "progress": null_progress,
        **context.ambient,
        CALL_CONTEXT: context.call_context,
        "user": context.principal,
        **context.resolved,
    }
    extra = form_kwargs(**pool_kwargs(form_kwargs, pool))
    if not isinstance(extra, Mapping):
        raise ImproperlyConfigured(
            f"{form_class.__qualname__}: form_kwargs returned {extra!r}; it returns a "
            "mapping of constructor keywords."
        )
    for key in extra:
        if key in BOUND_KEYWORDS:
            raise ImproperlyConfigured(
                f"{form_class.__qualname__}: form_kwargs returned {key!r}, which the bind "
                "sets itself from the call; return only the form's own keywords."
            )
    return extra
