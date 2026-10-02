"""What an operation returns, as a declaration, how a value is rendered, and for whom."""

from django_service_specs.output.annotate_output_schema import annotate_output_schema
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.output.project_payload import project_payload

__all__ = [
    "AudienceProjection",
    "FieldAudience",
    "FieldMarking",
    "Output",
    "OutputField",
    "Presenter",
    "annotate_output_schema",
    "audience_projection_for_spec",
    "project_payload",
]
