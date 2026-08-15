from pydantic import BaseModel, model_validator

from squawk.models import Location, TransportMode


class TemplateLeg(BaseModel):
    """A template for a leg of a shipment, used to generate legs with random dates."""

    mode: TransportMode
    dwell_time: list[int] | None
    port_of_loading: str
    port_of_discharge: str
    transit_time: list[int]


class TemplateShipment(BaseModel):
    """A template for a shipment, used to generate shipments with random dates and events."""

    reference: str
    mode: TransportMode
    place_of_receipt: str
    place_of_delivery: str
    legs: list[TemplateLeg]

    @model_validator(mode="after")
    def legs_must_chain(self):
        for prev, nxt in zip(self.legs, self.legs[1:]):
            if prev.port_of_discharge != nxt.port_of_loading:
                raise ValueError(
                    f"Leg chain broken: {prev.port_of_discharge} -> {nxt.port_of_loading}"
                )
        return self


class EvalData(BaseModel):
    """The data used to generate EvalCases, from data.yaml."""

    templates: list[TemplateShipment]
    locations: list[Location]
