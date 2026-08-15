from datetime import date, timedelta
from random import Random

from faker import Faker

from evals.generation.templates import TemplateShipment
from squawk.models import Contact, Event, Leg, Location, Shipment


def lookup_location(locode: str, locations_by_locode: dict[str, Location]) -> Location:
    """Look up a Location by its locode in the provided dictionary. Raises ValueError if not found."""
    try:
        return locations_by_locode[locode]
    except KeyError:
        raise ValueError(
            f"Location with locode {locode} not found. Define in input file."
        )


def generate_shipment(
    template_index: int,
    template: TemplateShipment,
    rng: Random,
    fake: Faker,
    locations: dict[str, Location],
) -> Shipment:
    """Generate a Shipment instance based on the provided template, using the given random number generator for date generation and the given seeded Faker for names, references and conveyances. The shipment's legs are created according to the template's specifications, and the shipment is assigned a unique ID and reference."""
    anchor_date = fake.date_between(start_date="-1y", end_date="today")

    legs: list[Leg] = []
    for index, leg_template in enumerate(template.legs):
        if index == 0:
            etd = anchor_date + timedelta(days=rng.randint(5, 10))
        else:
            if leg_template.dwell_time is None:
                raise ValueError(
                    f"Dwell time is not defined for leg {index} in template {template.reference}."
                )

            etd = legs[index - 1].eta + timedelta(
                days=rng.randint(leg_template.dwell_time[0], leg_template.dwell_time[1])
            )

        eta = etd + timedelta(
            days=rng.randint(leg_template.transit_time[0], leg_template.transit_time[1])
        )

        conveyance = (
            fake.vessel_voyage()
            if leg_template.mode == "ocean"
            else fake.flight_number()
        )

        leg = Leg(
            conveyance=conveyance,
            port_of_loading=lookup_location(leg_template.port_of_loading, locations),
            port_of_discharge=lookup_location(
                leg_template.port_of_discharge, locations
            ),
            etd=etd,
            atd=None,
            eta=eta,
            ata=None,
        )
        legs.append(leg)

    return Shipment(
        id=f"SHP-{template_index + 1:05d}",
        reference=fake.bothify("??######").upper(),
        booked_at=anchor_date,
        owner=Contact(name=fake.name(), email=fake.email()),
        customer_contact=Contact(name=fake.name(), email=fake.email()),
        transport_mode=template.mode,
        place_of_receipt=lookup_location(template.place_of_receipt, locations),
        port_of_loading=legs[0].port_of_loading,
        port_of_discharge=legs[-1].port_of_discharge,
        place_of_delivery=lookup_location(template.place_of_delivery, locations),
        legs=legs,
        events=[],
    )


def build_milestones(shipment: Shipment) -> list[tuple[str, date]]:
    """Build a list of milestones for the shipment, each represented as a tuple of (milestone_name, milestone_date). The milestones include booking, gate-in, departure and arrival for each leg, and final delivery. The list is sorted in chronological order."""
    milestones = []
    milestones.append(("booked", shipment.booked_at))
    milestones.append(
        ("gate_in", shipment.legs[0].etd - timedelta(days=1))
    )  # FIXME: randomize gate_in date
    for i, leg in enumerate(shipment.legs):
        milestones.append((f"departed_leg_{i}", leg.etd))
        milestones.append((f"arrived_leg_{i}", leg.eta))

    milestones.append(
        ("delivered", shipment.legs[-1].eta + timedelta(days=1))
    )  # FIXME: randomize delivered date
    return milestones


def apply_milestone(shipment: Shipment, milestone: tuple[str, date], rng: Random):
    """Apply a milestone to a shipment, updating its events and leg dates."""

    # FIXME: Implement randomization of event dates within a reasonable range around the milestone date.
    event_type, event_date = milestone
    if event_type == "booked":
        shipment.events.append(
            Event(
                event_type="booked",
                location=shipment.place_of_receipt,
                timestamp=event_date,
            )
        )
    elif event_type == "gate_in":
        shipment.events.append(
            Event(
                event_type="gate_in",
                location=shipment.port_of_loading,
                timestamp=event_date,
            )
        )
    elif event_type.startswith("departed_leg_"):
        leg_index = int(event_type.split("_")[-1])
        shipment.legs[leg_index].atd = event_date
        shipment.events.append(
            Event(
                event_type="departed",
                location=shipment.legs[leg_index].port_of_loading,
                timestamp=event_date,
            )
        )
    elif event_type.startswith("arrived_leg_"):
        leg_index = int(event_type.split("_")[-1])
        shipment.legs[leg_index].ata = event_date
        shipment.events.append(
            Event(
                event_type="arrived",
                location=shipment.legs[leg_index].port_of_discharge,
                timestamp=event_date,
            )
        )
    elif event_type == "delivered":
        shipment.events.append(
            Event(
                event_type="delivered",
                location=shipment.place_of_delivery,
                timestamp=event_date,
            )
        )
    else:
        raise ValueError(f"Unknown milestone type: {event_type}")

    return shipment


def progress_shipment(shipment: Shipment, rng: Random) -> Shipment:
    """Progress a shipment through its lifecycle upto a random milestone, generating events and updating dates."""
    milestones = build_milestones(shipment)  # flatten plan, sorted

    upto = rng.randint(
        1, len(milestones)
    )  # 1 = only booked, len(milestones) = all events

    for m in milestones[:upto]:
        shipment = apply_milestone(shipment, m, rng)  # append Event, stamp ATD/ATA
    shipment.current_time = shipment.events[
        -1
    ].timestamp  # date of last applied milestone: FIXME: randomize current_time between last milestone and next milestone
    return shipment


def shipment_tags(shipment: Shipment) -> list[str]:
    """Generate a list of tags for the shipment based on its characteristics, such as whether it is a transshipment or direct shipment, and its progress state (pre-departure, underway, or arrived)."""
    tags = []
    tags.append("transshipment" if len(shipment.legs) > 1 else "direct")

    # progress state
    if all(leg.atd is None for leg in shipment.legs):
        tags.append("pre_departure")
    elif all(leg.ata is not None for leg in shipment.legs):
        tags.append("arrived")
    else:
        tags.append("underway")

    return tags
