from typing import Any

from pydantic import BaseModel, computed_field

from squawk.models import Action


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


class EvalResult(BaseModel):
    """The result of scoring an agent on a single EvalCase."""

    case_id: str
    injector: str | None = None  # slicing metadata, copied from the EvalCase
    tags: list[str] = []
    should_act: bool = True  # what the expectation said, for the decision matrix
    actions: list[Action]
    error: str | None = None
    diff: ScoreDiff | None
    latency_ms: float | None


class SliceScore(BaseModel):
    """Micro-averaged scores over a slice of cases: sum counts first, divide once."""

    cases: int
    passed_cases: int
    errors: int = 0  # cases that never produced a scoreable reply
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


class EvalRunResults(BaseModel):
    """The results of an evaluation run, including the overall scores and the per-case results."""

    model: str
    system_prompt_hash: str
    metadata: dict[str, Any]
    summary: AggregateScore
    results: list[EvalResult]
