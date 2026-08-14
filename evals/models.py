from pydantic import BaseModel, computed_field, model_validator

from squawk.models import Action, IncomingEvent, Location, Shipment, TransportMode


class EvalData(BaseModel):
    """The data used to generate EvalCases, from data.yaml."""

    templates: list[TemplateShipment]
    locations: list[Location]


class TemplateLeg(BaseModel):
    """A template for a leg of a shipment, used to generate legs with random dates."""

    mode: TransportMode
    dwell_time: list[int] | None
    port_of_loading: str
    port_of_discharge: str
    transit_time: list[int]


class TemplateShipment(BaseModel):
    """A template for a shipment, used to generate shipments with random dates and events."""

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
    """What the agent is expected to do in response to an incoming event."""

    should_act: bool
    actions: list[Action]


class InjectionResult(BaseModel):
    """Result of injecting an event into a shipment, for scoring purposes."""

    event: IncomingEvent
    expectation: Expectation
    tags: list[str] = []


class EvalCase(BaseModel):
    """A single test case for an agent, including the shipment state, incoming event, and expected actions."""

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


class EvalResult(BaseModel):
    """The result of scoring an agent on a single EvalCase."""

    case_id: str
    model_name: str
    injector: str | None = None  # slicing metadata, copied from the EvalCase
    tags: list[str] = []
    should_act: bool = True  # what the expectation said, for the decision matrix
    actions: list[Action]
    error: str | None = None
    diff: ScoreDiff


class NearMiss(BaseModel):
    """Agent action that matched an expected action's type but not its payload."""

    expected: Action
    actual: Action
    reasons: list[str]  # human-readable field mismatches


class ScoreDiff(BaseModel):
    """Result of scoring one case."""

    passed: bool
    matched: list[Action]  # agent actions that matched an expectation exactly
    near_misses: list[NearMiss]  # right action type, wrong payload
    extra: list[Action]  # agent did these, expectation didn't ask (false positives)
    missing: list[Action]  # expectation asked, agent didn't do (false negatives)

    @computed_field
    @property
    def precision(self) -> float | None:
        """Of what the agent did, how much was right. None if agent did nothing."""
        denom = len(self.matched) + len(self.near_misses) + len(self.extra)
        return len(self.matched) / denom if denom else None

    @computed_field
    @property
    def recall(self) -> float | None:
        """Of what was expected, how much the agent did. None if nothing expected."""
        denom = len(self.matched) + len(self.near_misses) + len(self.missing)
        return len(self.matched) / denom if denom else None


class SliceScore(BaseModel):
    """Micro-averaged scores over a slice of cases: sum counts first, divide once."""

    cases: int
    passed_cases: int
    exact_matches: int
    near_misses: int
    false_positives: int
    false_negatives: int

    @computed_field
    @property
    def pass_rate(self) -> float | None:
        return self.passed_cases / self.cases if self.cases else None

    @computed_field
    @property
    def precision(self) -> float | None:
        denom = self.exact_matches + self.near_misses + self.false_positives
        return self.exact_matches / denom if denom else None

    @computed_field
    @property
    def recall(self) -> float | None:
        denom = self.exact_matches + self.near_misses + self.false_negatives
        return self.exact_matches / denom if denom else None


class DecisionMatrix(BaseModel):
    """Case-level act/stay-quiet confusion matrix, independent of which actions."""

    true_act: int  # should act, acted
    missed_act: int  # should act, stayed quiet
    false_alarm: int  # should stay quiet, acted
    true_quiet: int  # should stay quiet, stayed quiet

    @computed_field
    @property
    def false_alarm_rate(self) -> float | None:
        """Of the cases needing silence, how often the agent squawked anyway."""
        denom = self.false_alarm + self.true_quiet
        return self.false_alarm / denom if denom else None

    @computed_field
    @property
    def missed_act_rate(self) -> float | None:
        """Of the cases needing action, how often the agent stayed quiet."""
        denom = self.true_act + self.missed_act
        return self.missed_act / denom if denom else None


class AggregateScore(BaseModel):
    """Overall scores plus the slices that say where to look."""

    overall: SliceScore
    decisions: DecisionMatrix
    by_injector: dict[str, SliceScore]  # None injector reported as "clean"
    by_tag: dict[str, SliceScore]
    by_action_type: dict[str, SliceScore]
