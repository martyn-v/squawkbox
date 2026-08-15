from pydantic import BaseModel

from squawk.models import Action, IncomingEvent, Shipment


class Expectation(BaseModel):
    """What the agent is expected to do in response to an incoming event."""

    should_act: bool
    actions: list[Action] = []


class EvalCase(BaseModel):
    """A single test case for an agent, including the shipment state, incoming event, and expected actions."""

    # identity & reproducibility
    case_id: str  # "case-00042"
    seed: str  # the child seed string, e.g. "1-3-7"
    generator_version: str = "0.1.0"  # dataset provenance

    # slicing metadata (your results table columns)
    injector: str | None  # "arrival_delay"; clean cases come from RoutineEventInjector and carry the "clean" tag
    template_reference: str  # which lane/template
    tags: list[str] = []  # "transshipment", "underway", ...

    # what the agent sees
    shipment: Shipment  # state incl. Events and current_time
    incoming_event: IncomingEvent  # the event by the injector, or a routine event to verify cases where nothing should be done

    # what the scorer sees
    expectation: Expectation
