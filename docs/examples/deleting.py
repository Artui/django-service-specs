"""A delete that cascades through the same map the writes use."""

from __future__ import annotations

# --8<-- [start:delete]
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    delete_model,
    delete_relations,
)
from docs.examples.declaring import IsSignedIn
from docs.examples.relations import BOOKS
from tests.adapter_app.models import Author


def delete_author(*, instance: Author) -> tuple[int, ...]:
    # The database would take the books with the author and say nothing about
    # them. Cascading first, through the map the writes use, names each one.
    cascade = delete_relations(instance, relations=BOOKS)
    instance.delete()
    books = cascade.get_child_change("books")
    return books.deleted if books else ()


delete_author_spec = ServiceSpec(
    service=delete_author,
    permissions=[IsSignedIn()],
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
)
# --8<-- [end:delete]


# --8<-- [start:model]
retire_author_spec = ServiceSpec(
    # The books go first, through the map the writes use, then the author.
    service=delete_model(Author, relations=BOOKS),
    permissions=[IsSignedIn()],
    instance_selector_spec=delete_author_spec.instance_selector_spec,
)
# --8<-- [end:model]
