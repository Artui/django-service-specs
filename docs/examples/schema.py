"""JSON Schema from a spec's declarations: what it takes, and what it returns."""

from __future__ import annotations

# --8<-- [start:schema]
from django_service_specs import UnknownArguments
from django_service_specs.schema import spec_input_schema, spec_output_schema
from docs.examples.declaring import list_notes_spec
from docs.examples.relations import create_author_spec

# What a transport advertises for the notes list: its arguments, and its rows.
notes_input = spec_input_schema(list_notes_spec)
notes_output = spec_output_schema(list_notes_spec)

# The author write, as a transport that refuses an undeclared argument...
author_input = spec_input_schema(create_author_spec)
# ...and as one that drops it, which must not claim to refuse it.
lenient_author_input = spec_input_schema(
    create_author_spec, unknown_arguments=UnknownArguments.IGNORE
)
author_output = spec_output_schema(create_author_spec)
# --8<-- [end:schema]
