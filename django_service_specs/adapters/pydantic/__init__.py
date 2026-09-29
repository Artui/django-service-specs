"""The pydantic adapter: a pydantic model as a Validator and a Presenter.

Needs the ``pydantic`` extra (``pip install "django-service-specs[pydantic]"``).
Nothing outside this subpackage imports pydantic, and the package root does not
import this subpackage, so a project without pydantic never loads it.
"""

from django_service_specs.adapters.pydantic.pydantic_presenter import PydanticPresenter
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator

__all__ = ["PydanticPresenter", "PydanticValidator"]
