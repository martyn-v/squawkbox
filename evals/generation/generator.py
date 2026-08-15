from random import Random
import yaml
import os

from evals.faker.providers import make_faker
from evals.generation.injectors import (
    ArrivalDelayInjector,
    DepartureDelayInjector,
    RolledSailingInjector,
    RoutineEventInjector,
)
from evals.generation.shipments import (
    generate_shipment,
    progress_shipment,
    shipment_tags,
)
from evals.generation.templates import EvalData
from evals.logging import get_logger
from evals.models import EvalCase


logger = get_logger("generator")

INJECTORS = [
    ArrivalDelayInjector(),
    DepartureDelayInjector(),
    RoutineEventInjector(),
    RolledSailingInjector(),
]


def load_data(path: str) -> EvalData:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return EvalData.model_validate(data)


def generate(
    seed: int,
    variants: int,
    data_path: str,
    output_path: str,
):
    # Ensure output path exists
    if output_dir := os.path.dirname(output_path):
        os.makedirs(output_dir, exist_ok=True)

    logger.info("starting generator", seed=seed, variants=variants)
    data = load_data(data_path)
    locations_by_locode = {loc.locode: loc for loc in data.locations}

    counter = 0
    with open(output_path, "w") as f:
        for variant in range(variants):
            for index, template in enumerate(data.templates):
                child_seed = f"{seed}-{index}-{variant}"
                child_rng = Random(child_seed)
                # Created at a fixed point so the draw from child_rng doesn't shift as the pipeline evolves
                child_fake = make_faker(child_rng)

                # Generate a clean shipment
                shipment = generate_shipment(
                    index, template, child_rng, child_fake, locations_by_locode
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

                # Randomly select an applicable injector (RoutineEventInjector always applies, so there is always at least one) and inject an event into the shipment, generating the expected actions and tags for scoring.
                candidates = [inj for inj in INJECTORS if inj.is_applicable(shipment)]
                injector = child_rng.choice(candidates)
                result = injector.inject(shipment, child_rng, child_fake)
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

    logger.info("finished generator", total_cases=counter, output_path=output_path)
