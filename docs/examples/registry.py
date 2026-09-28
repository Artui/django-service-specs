"""The registry: one named, tagged set of operations that several transports read."""

from __future__ import annotations

# --8<-- [start:registry]
from django_service_specs import SpecRegistry
from docs.examples.declaring import list_notes_spec
from docs.examples.quickstart import rename_note_spec
from docs.examples.relations import create_author_spec, update_author_spec

registry = SpecRegistry()
registry.register("list_notes", list_notes_spec, tags=("notes", "read"))
registry.register("rename_note", rename_note_spec, tags=("notes", "write"))
registry.register("create_author", create_author_spec, tags=("catalogue", "write"))
registry.register("update_author", update_author_spec, tags=("catalogue", "write"))

# Each transport takes the view it exposes. Every derivation is a new registry,
# a snapshot sharing the spec objects, so neither view can change the other.
agent_tools = registry.by_tag("notes")  # list_notes, rename_note
command_line = registry.subset("create_author", "list_notes")  # in the order named
# --8<-- [end:registry]
