# django-service-specs

[![CI](https://github.com/Artui/django-service-specs/workflows/tests/badge.svg)](https://github.com/Artui/django-service-specs/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/django-service-specs.svg)](https://pypi.org/project/django-service-specs/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-service-specs.svg)](https://pypi.org/project/django-service-specs/)
[![Django versions](https://img.shields.io/pypi/djversions/django-service-specs.svg)](https://pypi.org/project/django-service-specs/)
[![Docs](https://img.shields.io/badge/docs-artui.github.io-blue.svg)](https://artui.github.io/django-service-specs/)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Artui/django-service-specs/gh-pages/coverage.json)](https://github.com/Artui/django-service-specs/actions/workflows/tests.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/pypi/l/django-service-specs.svg)](LICENSE)

A service contract for Django: declare an operation's parameters, permission
check, validation and output once, and dispatch it from any transport - an HTTP
view, an MCP tool, an agent tool, a management command or a background task.

Django is the base and the only dependency. Django REST Framework becomes one
adapter among several rather than a requirement, so a project with business
logic and no API framework can hand its operations to an agent, a command or a
queue without adopting one.

**Status: pre-release.** Nothing is published yet; the first release is 0.1.0.

## Install

```bash
pip install django-service-specs
```

## License

MIT
