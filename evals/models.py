from typing import Annotated, Literal
from pydantic import BaseModel, Field

from squawk.models import Action, IncomingEvent, Shipment


class Expectation(BaseModel):
    """What the agent is expected to do in response to an incoming event."""

    should_act: bool
    actions: list[Action] = []


class EvalCasesMeta(BaseModel):
    """Metadata for a set of evaluation cases."""

    kind: Literal["meta"] = "meta"
    generator_version: str = "0.1.0"  # dataset provenance
    seed: int
    generated_at: str
    git_sha: str
    case_count: int


class EvalCase(BaseModel):
    """A single test case for an agent, including the shipment state, incoming event, and expected actions."""

    kind: Literal["case"] = "case"
    # identity & reproducibility
    case_id: str  # "case-00042"
    seed: str  # the child seed string, e.g. "1-3-7"

    # slicing metadata (your results table columns)
    injector: (
        str | None
    )  # "arrival_delay"; clean cases come from RoutineEventInjector and carry the "clean" tag
    template_reference: str  # which lane/template
    tags: list[str] = []  # "transshipment", "underway", ...

    # what the agent sees
    shipment: Shipment  # state incl. Events and current_time
    incoming_event: IncomingEvent  # the event by the injector, or a routine event to verify cases where nothing should be done

    # what the scorer sees
    expectation: Expectation


EvalCasesRow = Annotated[
    EvalCasesMeta | EvalCase,
    Field(discriminator="kind"),
]
