"""What the docs site publishes, read from MkDocs' own file collection.

``docs/`` doubles as a Python package, so the suite imports and runs every
example as ``docs.examples.<name>``, and MkDocs copies every file under its
source directory that is not a page into the site verbatim. Without
``exclude_docs`` that published the example sources beside the pages, and the
bytecode a test run had compiled from them moments before the deploy.

The exclusion has to stay narrow: the release job writes ``coverage.json`` into
``docs/`` for the README badge, and relies on that same copying to ship it.
"""

from __future__ import annotations

from pathlib import Path

from mkdocs.config import load_config
from mkdocs.structure.files import get_files

CONFIG_FILE = Path(__file__).resolve().parents[2] / "mkdocs.yml"


def test_no_python_source_or_bytecode_is_published() -> None:
    config = load_config(str(CONFIG_FILE))

    published = [f.src_uri for f in get_files(config) if not f.inclusion.is_excluded()]

    assert "index.md" in published
    assert [uri for uri in published if uri.endswith((".py", ".pyc"))] == []


def test_the_coverage_badge_the_release_job_writes_still_ships() -> None:
    config = load_config(str(CONFIG_FILE))

    assert config.exclude_docs is not None
    assert not config.exclude_docs.match_file("coverage.json")
