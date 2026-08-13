from typing import Callable

from evals.models import AggregateScore, Expectation, ScoreDiff
from squawk.models import Action, NotifyAction, UpdatePropertyAction


Comparator = Callable[[Action, Action], bool]


def _cmp_notify(a: NotifyAction, b: NotifyAction) -> bool:
    return set(a.recipients) == set(b.recipients)


def _cmp_update_property(a: UpdatePropertyAction, b: UpdatePropertyAction) -> bool:
    return (a.path, a.new_value) == (b.path, b.new_value)


COMPARATORS: dict[str, Callable[..., bool]] = {
    "notify": lambda a, b: _cmp_notify(a, b),
    "update_property": lambda a, b: _cmp_update_property(a, b),
    "escalate": lambda a, b: True,
}


def _matches(agent_action: Action, expected_action: Action) -> bool:
    if agent_action.type != expected_action.type:
        return False
    comparator = COMPARATORS.get(agent_action.type)
    if comparator is None:
        raise ValueError(
            f"No comparator registered for action type: {agent_action.type}"
        )
    return comparator(agent_action, expected_action)


def score(expectation: Expectation, actions: list[Action]) -> ScoreDiff:
    """Score agent actions against an expectation with one-to-one matching."""
    unclaimed = list(expectation.actions)  # copy; claimed items get removed
    matched: list[Action] = []
    extra: list[Action] = []

    for action in actions:
        claimed = next(
            (exp for exp in unclaimed if _matches(action, exp)),
            None,
        )
        if claimed is not None:
            unclaimed.remove(claimed)
            matched.append(action)
        else:
            extra.append(action)

    # whatever the agent never claimed was missed
    missing = unclaimed

    return ScoreDiff(
        passed=not extra and not missing,
        matched=matched,
        extra=extra,
        missing=missing,
    )


def aggregate_scores(diffs: list[ScoreDiff]) -> AggregateScore:
    return AggregateScore(
        cases=len(diffs),
        true_positives=sum(len(d.matched) for d in diffs),
        false_positives=sum(len(d.extra) for d in diffs),
        false_negatives=sum(len(d.missing) for d in diffs),
    )
