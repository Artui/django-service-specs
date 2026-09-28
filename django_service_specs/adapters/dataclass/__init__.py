"""The reference adapter: a standard-library dataclass as a Validator and a Presenter."""

from django_service_specs.adapters.dataclass.dataclass_presenter import DataclassPresenter
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator

__all__ = ["DataclassPresenter", "DataclassValidator"]
