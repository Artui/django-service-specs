"""``NON_FIELD_KEYS`` - the keys a message about the whole input sits under."""

from __future__ import annotations

from typing import Final

from django.core.exceptions import NON_FIELD_ERRORS as DJANGO_NON_FIELD_ERRORS

from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS

NON_FIELD_KEYS: Final = (NON_FIELD_ERRORS, DJANGO_NON_FIELD_ERRORS)
"""The keys a message about the whole input sits under: the kernel's, and Django's.

Django's is here because a service re-raising a model's ``message_dict`` as a
``ServiceValidationError`` carries its form-wide messages under ``"__all__"``.
Neither adds a step to the path a message is placed or printed with. Both are
held by test_a_refusal_tree_is_read_as_paths_to_messages, which fails with
either left out."""
