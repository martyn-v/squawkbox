from datetime import date
from typing import Annotated, Any
from typing_extensions import Literal
from pydantic import BaseModel, ConfigDict, Field


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
    conveyance: str
    port_of_loading: Location
    port_of_discharge: Location
    etd: date
    atd: date | None
    eta: date
    ata: date | None


class Contact(BaseModel):
    # Frozen so contacts hash by value
    model_config = ConfigDict(frozen=True)

    name: str
    email: str


class Shipment(BaseModel):
    id: str
    reference: str
    booked_at: date
    owner: Contact
    customer_contact: Contact
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


class UpdatePropertyAction(BaseModel):
    """Action that updates a property on the shipment, such as correcting an ETA or port. The path is a JSON pointer to the property, and new_value is the corrected value."""

    type: Literal["update_property"] = "update_property"
    path: str
    new_value: Any


class NotifyAction(BaseModel):
    """Action that notifies a human operator about something. The message is judge material only, never diffed."""

    type: Literal["notify"] = "notify"
    recipients: Annotated[list[Contact], "List of people to notify"]
    message: str | None = None  # judge material only, never diffed


class EscalateAction(BaseModel):
    """Action that escalates the shipment to a human operator, such as when downstream intervention is required. The reason is judge material only, never diffed."""

    type: Literal["escalate"] = "escalate"
    reason: str | None = None  # judge material only, never diffed


Action = Annotated[
    UpdatePropertyAction | NotifyAction | EscalateAction,
    Field(discriminator="type"),
]


class AgentReply(BaseModel):
    actions: list[Action]
