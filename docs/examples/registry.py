"""The registry: one named, tagged set of operations that several transports read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    SpecRegistry,
    kernel_spec,
)
from docs.examples.declaring import IsSignedIn, list_notes_spec, notes_of
from docs.examples.quickstart import rename_note_spec
from docs.examples.relations import create_author_spec, update_author_spec

# --8<-- [start:registry]
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


# --8<-- [start:source]
@dataclass(frozen=True)
class OtherLibrarysListing:
    """A read declared in another library's vocabulary, compiled on demand."""

    ordering: str = "title"

    def as_kernel_spec(self) -> SelectorSpec:
        return SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=[IsSignedIn()])

    def agent_contract(self) -> dict[str, Any]:
        return {"ordering": self.ordering}


listing = OtherLibrarysListing()
mixed = SpecRegistry()
mixed.register("legacy_notes", listing, tags=("notes", "read"))
mixed.register("list_notes", list_notes_spec, tags=("notes", "read"))

entry = mixed.get("legacy_notes")
assert entry is not None and entry.spec is listing  # kept as registered
compiled = kernel_spec(listing)  # compiled once; the same object every time
contracts = [e.agent_contract for e in mixed]  # [{"ordering": "title"}, None]
# --8<-- [end:source]


# --8<-- [start:derive]
# The same listing for the command line, which offers a search and no choice
# of ordering: ``reads=`` is the variant's whole ``reads``, so ``ordering`` is
# no longer an argument and the selector's own default answers for it.
search_only = list_notes_spec.derive(
    reads=Parameters.of(Parameter("search", "string", help="Part of the title, in any case.")),
)
# --8<-- [end:derive]

# --8<-- [start:replace]
# The command line is handed a registry with the variant under the operation's
# own name; every other transport keeps reading ``registry``, and the base.
command_line_registry = registry.replace("list_notes", search_only)
# --8<-- [end:replace]
