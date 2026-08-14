from collections import defaultdict
from typing import Callable

from evals.models import (
    AggregateScore,
    DecisionMatrix,
    EvalResult,
    Expectation,
    NearMiss,
    ScoreDiff,
    SliceScore,
)
from squawk.models import Action, NotifyAction, UpdatePropertyAction


# Comparators return the list of field mismatches between an agent action and an
# expected action of the same type; empty means exact match. The non-empty case
# doubles as the near-miss explanation ("right action, wrong payload, here's what
# differs"), which is why these return human-readable strings rather than a bool.
Comparator = Callable[[Action, Action], list[str]]


def _cmp_notify(a: NotifyAction, b: NotifyAction) -> list[str]:
    """Compare two NotifyAction instances and return a list of human-readable reasons for any mismatches in their recipients."""
    got, want = set(a.recipients), set(b.recipients)
    reasons = []
    if missing := want - got:
        reasons.append(f"missing recipients: {sorted(missing, key=lambda c: c.email)}")
    if unexpected := got - want:
        reasons.append(
            f"unexpected recipients: {sorted(unexpected, key=lambda c: c.email)}"
        )
    return reasons


def _cmp_update_property(a: UpdatePropertyAction, b: UpdatePropertyAction) -> list[str]:
    """Compare two UpdatePropertyAction instances and return a list of human-readable reasons for any mismatches in their paths or new values."""
    # A wrong path makes the value comparison meaningless (different property
    # entirely), so it short-circuits rather than stacking a second reason.
    if a.path != b.path:
        return [f"path: got {a.path!r}, expected {b.path!r}"]
    if a.new_value != b.new_value:
        return [f"{a.path}: got {a.new_value!r}, expected {b.new_value!r}"]
    return []


COMPARATORS: dict[str, Callable[..., list[str]]] = {
    "notify": lambda a, b: _cmp_notify(a, b),
    "update_property": lambda a, b: _cmp_update_property(a, b),
    # escalate has no diffable payload (reason is judge material), so any
    # escalate matches any expected escalate exactly
    "escalate": lambda a, b: [],
}


def _mismatches(agent_action: Action, expected_action: Action) -> list[str]:
    """Return a list of human-readable reasons why the agent action does not match the expected action, or an empty list if they match exactly."""
    comparator = COMPARATORS.get(agent_action.type)
    if comparator is None:
        raise ValueError(
            f"No comparator registered for action type: {agent_action.type}"
        )
    return comparator(agent_action, expected_action)


def score(expectation: Expectation, actions: list[Action]) -> ScoreDiff:
    """Score agent actions against an expectation with one-to-one matching.

    Two passes: exact matches claim expectations first, then leftover agent
    actions pair with same-type expectations as near misses (closest first).

    The exact pass must complete before any near-miss pairing so an
    almost-right action can never steal an expectation that a later, exactly
    right action would have claimed. A near miss consumes both its actions —
    the pair reports once in near_misses instead of once in extra plus once
    in missing, which is what links "what the agent did" to "what it should
    have done". Near misses still count as failures: passed requires all
    three failure buckets empty, and ScoreDiff's precision/recall count them
    against the agent.
    """
    unclaimed = list(expectation.actions)  # copy; claimed items get removed
    matched: list[Action] = []
    near_misses: list[NearMiss] = []
    extra: list[Action] = []
    unmatched: list[Action] = []

    for action in actions:
        exact = next(
            (
                exp
                for exp in unclaimed
                if exp.type == action.type and not _mismatches(action, exp)
            ),
            None,
        )
        if exact is not None:
            unclaimed.remove(exact)
            matched.append(action)
        else:
            unmatched.append(action)

    for action in unmatched:
        # Near misses only pair within the same action type; a notify can
        # never be "almost" an update_property. Fewest field mismatches wins
        # when several expectations of the type are still unclaimed.
        candidates = [exp for exp in unclaimed if exp.type == action.type]
        if candidates:
            best = min(candidates, key=lambda exp: len(_mismatches(action, exp)))
            unclaimed.remove(best)
            near_misses.append(
                NearMiss(
                    expected=best,
                    actual=action,
                    reasons=_mismatches(action, best),
                )
            )
        else:
            extra.append(action)

    # whatever the agent never claimed was missed
    missing = unclaimed

    return ScoreDiff(
        passed=not near_misses and not extra and not missing,
        matched=matched,
        near_misses=near_misses,
        extra=extra,
        missing=missing,
    )


def _slice_score(results: list[EvalResult]) -> SliceScore:
    """Micro-average a group of results: sum raw counts, let SliceScore divide."""
    return SliceScore(
        cases=len(results),
        passed_cases=sum(r.diff.passed for r in results),
        exact_matches=sum(len(r.diff.matched) for r in results),
        near_misses=sum(len(r.diff.near_misses) for r in results),
        false_positives=sum(len(r.diff.extra) for r in results),
        false_negatives=sum(len(r.diff.missing) for r in results),
    )


def _by_action_type(results: list[EvalResult]) -> dict[str, SliceScore]:
    """Regroup diff entries by action type: is the agent bad at notify or at
    update_property?

    Unlike the other slices this cuts across cases, so "cases" means cases in
    which the type appeared at all (in the agent's output or the expectation),
    and a case counts as passed for a type when that type contributed no near
    misses, extras, or missing actions there. Near misses tally under the
    expected action's type — the agent was trying to satisfy that expectation.
    """
    tallies: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        seen: set[str] = set()
        failed: set[str] = set()
        for action in r.diff.matched:
            tallies[action.type]["exact"] += 1
            seen.add(action.type)
        for nm in r.diff.near_misses:
            tallies[nm.expected.type]["near"] += 1
            seen.add(nm.expected.type)
            failed.add(nm.expected.type)
        for action in r.diff.extra:
            tallies[action.type]["extra"] += 1
            seen.add(action.type)
            failed.add(action.type)
        for action in r.diff.missing:
            tallies[action.type]["missing"] += 1
            seen.add(action.type)
            failed.add(action.type)
        for action_type in seen:
            tallies[action_type]["cases"] += 1
            if action_type not in failed:
                tallies[action_type]["passed"] += 1

    return {
        action_type: SliceScore(
            cases=t["cases"],
            passed_cases=t["passed"],
            exact_matches=t["exact"],
            near_misses=t["near"],
            false_positives=t["extra"],
            false_negatives=t["missing"],
        )
        for action_type, t in sorted(tallies.items())
    }


def aggregate_scores(results: list[EvalResult]) -> AggregateScore:
    """Roll many results into overall scores plus the slices that say where to look.

    Slices: by injector (fault type; injector=None cases group under "clean"),
    by tag (a case appears in every one of its tags), and by action type. The
    decision matrix scores each case's act/stay-quiet call — should_act comes
    from the expectation, "acted" means the agent emitted any action at all,
    right or wrong. That separates "squawks when it shouldn't" (false_alarm)
    from "acts but picks wrong actions", which only the action-level slices see.
    """
    by_injector: defaultdict[str, list[EvalResult]] = defaultdict(list)
    by_tag: defaultdict[str, list[EvalResult]] = defaultdict(list)
    for r in results:
        by_injector[r.injector or "clean"].append(r)
        for tag in r.tags:
            by_tag[tag].append(r)

    decisions = DecisionMatrix(
        true_act=sum(1 for r in results if r.should_act and r.actions),
        missed_act=sum(1 for r in results if r.should_act and not r.actions),
        false_alarm=sum(1 for r in results if not r.should_act and r.actions),
        true_quiet=sum(1 for r in results if not r.should_act and not r.actions),
    )

    return AggregateScore(
        overall=_slice_score(results),
        decisions=decisions,
        by_injector={k: _slice_score(v) for k, v in sorted(by_injector.items())},
        by_tag={k: _slice_score(v) for k, v in sorted(by_tag.items())},
        by_action_type=_by_action_type(results),
    )
