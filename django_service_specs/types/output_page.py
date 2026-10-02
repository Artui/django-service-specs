"""``OutputPage`` - one page of a list's rows, and how to describe it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutputPage:
    """One page of rows, plus what a caller needs to know to ask for the next.

    What [`paginate_output`][django_service_specs.dispatch.paginate_output.paginate_output]
    returns, and the payload
    [`spec_output_schema(paginate=True)`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    describes. The schema and the shaper are one mechanism in two places, so
    they are kept beside each other: a transport that wraps its pages and one
    that returns a bare list, against a schema claiming the envelope for both,
    is the drift this exists to prevent.

    ``items`` is the slice itself, unpresented: presenting needs the spec and
    belongs to the caller. Hand the presented result back to
    [`envelope`][django_service_specs.types.output_page.OutputPage.envelope]
    to get the wire shape.
    """

    #: The rows on this page, as sliced: a queryset slice or a sequence slice.
    items: Any
    #: The page actually served, which is not always the page asked for.
    page: int
    #: The page size actually applied, after any ceiling.
    limit: int
    #: How many rows there are in total, counted before the slice.
    total: int

    @property
    def total_pages(self) -> int:
        """How many pages exist at this ``limit``. At least one, even for no rows.

        An empty result is one empty page rather than zero pages: ``page`` is
        1-based and the page served for an empty result is 1, so reporting 0
        would describe a page the caller was just handed as not existing.
        """
        return max(1, -(-self.total // self.limit))

    @property
    def has_next(self) -> bool:
        """Whether asking for ``page + 1`` would return anything."""
        return self.page < self.total_pages

    def envelope(self, rendered: Any) -> dict[str, Any]:
        """Wrap already-presented rows in the published paging envelope.

        ``rendered`` rather than ``items`` because an audience projection lands
        on the rows and never on the envelope: ``page``, ``totalPages`` and
        ``hasNext`` are this shape's own keys and belong to no ``Output``, so a
        projection walking them would look for markings that cannot exist.
        """
        return {
            "items": rendered,
            "page": self.page,
            "totalPages": self.total_pages,
            "hasNext": self.has_next,
        }
