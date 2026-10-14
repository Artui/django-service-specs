"""``NON_FIELD_ERRORS`` - the key a node's own message sits under."""

from __future__ import annotations

from typing import Final

NON_FIELD_ERRORS: Final = "non_field_errors"
"""The key a message about a node itself sits under, beside its fields' messages.

A row that is not an object has no field to hang the message on, so it goes
here inside the row: ``{"books": {1: {"non_field_errors": ["..."]}}}``. It is
Django's and DRF's spelling of the same idea, so a transport rendering either's
errors reads the kernel's without a translation table."""
