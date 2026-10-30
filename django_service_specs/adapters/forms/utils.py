"""Helpers shared by the forms adapter's Validator and ``form_keywords``, which builds its keywords off dispatch."""

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
    """What ``form_kwargs`` returns for this call, or nothing when there is none.

    Its pool is the context's ``ambient`` over ``null_progress`` as
    ``progress``, so the name is in every pool, as ``base_pool`` promises,
    with ``ambient`` empty in ``bind_arguments`` handed no ``pool_seeds`` and
    in a context built without seeds, holding every seed under
    ``bind_arguments`` handed them, and the seeds it resolved under ``form_keywords``
    (test_only_the_seed_form_kwargs_names_resolves). ``user`` is laid over
    ``ambient``, so the principal is ``user`` on every path, the two being
    one object on dispatch, and the context's ``resolved`` last: its names
    are reserved, so no seed shares one. The call's context is there too, as
    the context's own dict, handed to a ``form_kwargs`` naming it
    (test_form_kwargs_naming_the_call_context_is_handed_the_very_dict) and,
    as everywhere, never to one taking ``**kwargs``. So are the call's
    ``request`` and ``view``, read off that dict, unless ``ambient`` holds a
    seed registered under the name, which is the value then
    (test_a_form_s_form_kwargs_is_handed_the_context_s_request_and_view, and
    test_a_seed_registered_under_the_name_outranks_the_context_s_value in
    ``form_keywords``' tests). Each is held by its own test:
    test_off_dispatch_it_meets_the_principal_as_user_and_no_seed
    (``progress``),
    test_a_hand_built_context_s_user_is_still_the_principal (``user``) and
    test_an_update_hands_it_the_row_itself_and_the_form_a_copy
    (``resolved``).
    """
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
    # Every key in the set is held by its own case of
    # test_refuses_a_key_the_bind_sets_itself, on a form and a ModelForm.
    for key in extra:
        if key in BOUND_KEYWORDS:
            raise ImproperlyConfigured(
                f"{form_class.__qualname__}: form_kwargs returned {key!r}, which the bind "
                "sets itself from the call; return only the form's own keywords."
            )
    return extra
