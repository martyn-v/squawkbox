from datetime import date
from typing import Annotated, Any
from typing_extensions import Literal
from pydantic import BaseModel, Field


type EventType = Literal["booked", "gate_in", "departed", "arrived", "delivered"]
type TransportMode = Literal["ocean", "air"]


class Location(BaseModel):
    locode: str
    name: str


class Event(BaseModel):
    event_type: EventType
    location: Location | None
    timestamp: date


class Leg(BaseModel):
    port_of_loading: Location
    port_of_discharge: Location
    etd: date
    atd: date | None
    eta: date
    ata: date | None


class Contact(BaseModel):
    email: str | None


class Shipment(BaseModel):
    id: str
    reference: str
    booked_at: date
    contact: Contact
    transport_mode: TransportMode
    place_of_receipt: Location
    port_of_loading: Location
    port_of_discharge: Location
    place_of_delivery: Location
    legs: list[Leg]
    events: list[Event]
    current_time: date | None = None


class ArrivalDelayEvent(BaseModel):
    type: Literal["arrival_delay"] = "arrival_delay"
    leg_index: int
    delay_days: int


class RoutineEvent(BaseModel):
    type: Literal["eta_confirmed"] = "eta_confirmed"
    leg_index: int
    eta: date


IncomingEvent = Annotated[
    ArrivalDelayEvent | RoutineEvent,
    Field(discriminator="type"),
]


class UpdatePropertyAction(BaseModel):
    type: Literal["update_property"] = "update_property"
    path: str
    new_value: Any


class NotifyAction(BaseModel):
    type: Literal["notify"] = "notify"
    recipients: list[str]
    message: str | None = None  # judge material only, never diffed


class EscalateAction(BaseModel):
    type: Literal["escalate"] = "escalate"
    reason: str | None = None  # judge material only, never diffed


Action = Annotated[
    UpdatePropertyAction | NotifyAction | EscalateAction,
    Field(discriminator="type"),
]


class AgentReply(BaseModel):
    actions: list[Action]
