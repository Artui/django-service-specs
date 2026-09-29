"""JSON Schema for what an operation takes and returns, emitted from its declarations."""

from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.schema.spec_output_schema import spec_output_schema

__all__ = ["output_schema", "parameters_schema", "spec_input_schema", "spec_output_schema"]
