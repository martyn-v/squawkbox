from datetime import date
from typing import Annotated
from typing_extensions import Literal
from pydantic import BaseModel, Field


class ArrivalDelayEvent(BaseModel):
    type: Literal["arrival_delay"] = "arrival_delay"
    leg_index: int
    delay_days: int


class DepartureDelayEvent(BaseModel):
    type: Literal["departure_delay"] = "departure_delay"
    leg_index: int
    delay_days: int


class RolledSailingEvent(BaseModel):
    type: Literal["rolled_sailing"] = "rolled_sailing"
    leg_index: int
    new_conveyance: str
    new_etd: date
    new_eta: date


class RoutineEvent(BaseModel):
    type: Literal["eta_confirmed"] = "eta_confirmed"
    leg_index: int
    eta: date


IncomingEvent = Annotated[
    ArrivalDelayEvent | DepartureDelayEvent | RolledSailingEvent | RoutineEvent,
    Field(discriminator="type"),
]
