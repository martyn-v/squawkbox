from datetime import date
from typing_extensions import Literal
from pydantic import BaseModel, ConfigDict

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
