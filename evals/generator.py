from datetime import date, timedelta
from random import Random
import yaml
import os
from faker import Faker

from evals.models import (
    EvalCase,
    EvalData,
    Expectation,
    TemplateShipment,
)
from evals.scenarios import ArrivalDelayInjector, DepartureDelayInjector
from evals.logging import get_logger
from squawk.models import Contact, Event, Leg, Location, Shipment, RoutineEvent


logger = get_logger("generator")


def load_data(path: str) -> EvalData:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return EvalData.model_validate(data)


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
    locations: dict[str, Location],
) -> Shipment:
    """Generate a Shipment instance based on the provided template, using the given random number generator for date generation. The shipment's legs are created according to the template's specifications, and the shipment is assigned a unique ID and reference."""
    fake = Faker()
    fake.seed_instance(rng.randint(0, 2**32))
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
        leg = Leg(
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
        contact=Contact(email=fake.email()),
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


INJECTORS = [ArrivalDelayInjector(), DepartureDelayInjector()]
DEFAULT_SEED = 42
VARIANTS_PER_TEMPLATE = 2
DEFAULT_DATA_PATH = "evals/artifacts/data.yaml"
DEFAULT_OUTPUT_PATH = "evals/fixtures/cases.jsonl"


if __name__ == "__main__":
    # Ensure output path exists
    os.makedirs(os.path.dirname(DEFAULT_OUTPUT_PATH), exist_ok=True)

    logger.info("starting generator", seed=DEFAULT_SEED, variants=VARIANTS_PER_TEMPLATE)
    data = load_data(DEFAULT_DATA_PATH)
    locations_by_locode = {loc.locode: loc for loc in data.locations}
    seed = DEFAULT_SEED
    counter = 0
    with open(DEFAULT_OUTPUT_PATH, "w") as f:
        for variant in range(VARIANTS_PER_TEMPLATE):
            for index, template in enumerate(data.templates):
                child_seed = f"{seed}-{index}-{variant}"
                child_rng = Random(child_seed)

                # Generate a clean shipment
                shipment = generate_shipment(
                    index, template, child_rng, locations_by_locode
                )
                logger.debug(
                    "generated shipment",
                    shipment_id=shipment.id,
                    template=template.reference,
                )

                # Progress the shipment through its lifecycle to a random milestone, generating events and updating leg dates accordingly.
                shipment = progress_shipment(shipment, child_rng)
                logger.debug(
                    "progressed shipment",
                    shipment_id=shipment.id,
                    last_event=shipment.events[-1].event_type
                    if shipment.events
                    else None,
                )

                candidates = [inj for inj in INJECTORS if inj.is_applicable(shipment)]

                if candidates:
                    # Randomly select an applicable injector and inject an event into the shipment, generating the expected actions and tags for scoring.
                    injector = child_rng.choice(candidates)
                    result = injector.inject(shipment, child_rng)
                    injector_name, event, expectation, extra_tags = (
                        injector.__class__.__name__,
                        result.event,
                        result.expectation,
                        result.tags,
                    )
                    logger.debug(
                        "injected event",
                        shipment_id=shipment.id,
                        injector=injector_name,
                        event_type=event.__class__.__name__,
                    )
                else:
                    # No applicable injectors; generate a clean case with a routine event and no expected actions. The case is tagged as "clean" for scoring purposes.
                    injector_name, event, expectation, extra_tags = (
                        None,
                        RoutineEvent(
                            leg_index=0, eta=shipment.legs[0].eta
                        ),  # FIXME: this should calculate based on the actual shipment, same as an injector
                        Expectation(should_act=False, actions=[]),
                        ["clean"],
                    )
                    logger.debug(
                        "no applicable injectors",
                        shipment_id=shipment.id,
                        event_type=event.__class__.__name__,
                    )

                case = EvalCase(
                    case_id=f"case-{index:05d}-{variant}",
                    seed=child_seed,
                    injector=injector_name,
                    template_reference=template.reference,
                    tags=shipment_tags(shipment) + extra_tags,
                    shipment=shipment,
                    incoming_event=event,
                    expectation=expectation,
                )
                f.write(case.model_dump_json() + "\n")
                counter += 1

    logger.info(
        "finished generator", total_cases=counter, output_path=DEFAULT_OUTPUT_PATH
    )
