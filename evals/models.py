from pydantic import BaseModel, computed_field, model_validator

from squawk.models import Action, IncomingEvent, Location, Shipment, TransportMode


class EvalData(BaseModel):
    templates: list[TemplateShipment]
    locations: list[Location]


class TemplateLeg(BaseModel):
    """A template for a leg of a shipment, used to generate legs with random dates. From data.yaml."""

    mode: TransportMode
    dwell_time: list[int] | None
    port_of_loading: str
    port_of_discharge: str
    transit_time: list[int]


class TemplateShipment(BaseModel):
    """A template for a shipment, used to generate shipments with random dates and events. From data.yaml."""

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


class Expectation(BaseModel):
    should_act: bool
    actions: list[Action]


class InjectionResult(BaseModel):
    event: IncomingEvent
    expectation: Expectation
    tags: list[str] = []


class EvalCase(BaseModel):
    # identity & reproducibility
    case_id: str  # "case-00042"
    seed: str  # the child seed string, e.g. "1-3-7"
    generator_version: str = "0.1.0"  # dataset provenance

    # slicing metadata (your results table columns)
    injector: str | None  # "arrival_delay", None = clean case
    template_reference: str  # which lane/template
    tags: list[str] = []  # "transshipment", "underway", ...

    # what the agent sees
    shipment: Shipment  # state incl. Events and current_time
    incoming_event: IncomingEvent  # the event by the injector, or a routine event to verify cases where nothing should be done

    # what the scorer sees
    expectation: Expectation

    # what the agent generated (for scoring)
    actions: list[Action] | None = (
        None  # filled in by the runner, not part of the case itself
    )


class EvalResult(BaseModel):
    case_id: str
    model_name: str
    actions: list[Action]
    error: str | None = None
    diff: ScoreDiff


class ScoreDiff(BaseModel):
    """Result of scoring one case."""

    passed: bool
    matched: list[Action]  # agent actions that matched an expectation
    extra: list[Action]  # agent did these, expectation didn't ask (false positives)
    missing: list[Action]  # expectation asked, agent didn't do (false negatives)

    @computed_field
    @property
    def precision(self) -> float | None:
        """Of what the agent did, how much was right. None if agent did nothing."""
        denom = len(self.matched) + len(self.extra)
        return len(self.matched) / denom if denom else None

    @computed_field
    @property
    def recall(self) -> float | None:
        """Of what was expected, how much the agent did. None if nothing expected."""
        denom = len(self.matched) + len(self.missing)
        return len(self.matched) / denom if denom else None


class AggregateScore(BaseModel):
    """Micro-averaged scores over many cases: sum counts first, divide once."""

    cases: int
    true_positives: int
    false_positives: int
    false_negatives: int

    @computed_field
    @property
    def precision(self) -> float | None:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else None

    @computed_field
    @property
    def recall(self) -> float | None:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else None
