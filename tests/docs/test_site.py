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
