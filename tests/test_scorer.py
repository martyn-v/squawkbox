from evals.models import Expectation
from evals.scoring.results import EvalResult, ScoreDiff
from evals.scoring.scorer import aggregate_scores, score
from squawk.models import (
    Contact,
    EscalateAction,
    NotifyAction,
    UpdatePropertyAction,
)

ALICE = Contact(name="Alice", email="alice@example.com")
BOB = Contact(name="Bob", email="bob@example.com")


def expect(*actions) -> Expectation:
    return Expectation(should_act=bool(actions), actions=list(actions))


def update(path: str = "legs[0].eta", value: str = "2026-09-12") -> UpdatePropertyAction:
    return UpdatePropertyAction(path=path, new_value=value)


def notify(*recipients: Contact) -> NotifyAction:
    return NotifyAction(recipients=list(recipients))


class TestScoreExactMatching:
    def test_quiet_case_passes(self):
        diff = score(expect(), [])
        assert diff.passed
        assert not diff.matched
        assert not diff.near_misses
        assert not diff.extra
        assert not diff.missing

    def test_full_exact_match_passes(self):
        expected = expect(update(), notify(ALICE), EscalateAction())
        diff = score(expected, [update(), notify(ALICE), EscalateAction()])
        assert diff.passed
        assert len(diff.matched) == 3

    def test_order_does_not_matter(self):
        expected = expect(update(), notify(ALICE))
        diff = score(expected, [notify(ALICE), update()])
        assert diff.passed

    def test_escalate_matches_regardless_of_reason(self):
        # reason is judge material, never diffed
        diff = score(
            expect(EscalateAction(reason="rebook leg 2")),
            [EscalateAction(reason="totally different reason")],
        )
        assert diff.passed

    def test_missing_actions_are_false_negatives(self):
        expected = expect(update(), notify(ALICE))
        diff = score(expected, [])
        assert not diff.passed
        assert len(diff.missing) == 2
        assert diff.recall == 0.0
        assert diff.precision is None  # agent did nothing

    def test_extra_actions_are_false_positives(self):
        diff = score(expect(), [EscalateAction()])
        assert not diff.passed
        assert diff.extra == [EscalateAction()]
        assert diff.precision == 0.0
        assert diff.recall is None  # nothing expected

    def test_duplicate_action_becomes_extra(self):
        diff = score(expect(EscalateAction()), [EscalateAction(), EscalateAction()])
        assert not diff.passed
        assert len(diff.matched) == 1
        assert len(diff.extra) == 1


class TestScoreNearMisses:
    def test_notify_wrong_recipient_is_near_miss(self):
        diff = score(expect(notify(ALICE)), [notify(BOB)])
        assert not diff.passed
        assert len(diff.near_misses) == 1
        nm = diff.near_misses[0]
        assert nm.expected == notify(ALICE)
        assert nm.actual == notify(BOB)
        assert any("missing recipients" in r for r in nm.reasons)
        assert any("unexpected recipients" in r for r in nm.reasons)

    def test_update_wrong_value_is_near_miss(self):
        diff = score(
            expect(update(value="2026-09-12")), [update(value="2026-09-13")]
        )
        assert len(diff.near_misses) == 1
        [reason] = diff.near_misses[0].reasons
        assert "2026-09-13" in reason and "2026-09-12" in reason

    def test_update_wrong_path_short_circuits_value(self):
        # A wrong path yields one reason; the value comparison is meaningless
        diff = score(
            expect(update(path="legs[1].eta")), [update(path="legs[0].eta")]
        )
        [reason] = diff.near_misses[0].reasons
        assert reason.startswith("path:")

    def test_near_miss_consumes_both_actions(self):
        # The pair reports once in near_misses, not once in extra plus once in missing
        diff = score(expect(notify(ALICE)), [notify(BOB)])
        assert not diff.extra
        assert not diff.missing

    def test_near_miss_never_pairs_across_types(self):
        diff = score(expect(update()), [notify(ALICE)])
        assert not diff.near_misses
        assert diff.extra == [notify(ALICE)]
        assert diff.missing == [update()]

    def test_exact_match_cannot_be_stolen_by_earlier_near_miss(self):
        # The exact pass completes before near-miss pairing, so the
        # almost-right notify(BOB) must not claim the expectation that the
        # later, exactly-right notify(ALICE) satisfies.
        diff = score(expect(notify(ALICE)), [notify(BOB), notify(ALICE)])
        assert diff.matched == [notify(ALICE)]
        assert not diff.near_misses
        assert diff.extra == [notify(BOB)]

    def test_near_miss_pairs_with_fewest_mismatches(self):
        # notify(BOB) vs notify(ALICE): 2 reasons (missing + unexpected)
        # notify(BOB) vs notify(ALICE, BOB): 1 reason (missing ALICE)
        diff = score(expect(notify(ALICE), notify(ALICE, BOB)), [notify(BOB)])
        assert diff.near_misses[0].expected == notify(ALICE, BOB)
        assert diff.missing == [notify(ALICE)]


class TestScoreDiffMetrics:
    def test_precision_and_recall_count_near_misses_against_agent(self):
        expected = expect(update(), notify(ALICE), EscalateAction())
        actions = [update(), notify(BOB), update(path="legs[9].ata")]
        diff = score(expected, actions)
        # matched: update; near miss: notify; extra: second update; missing: escalate
        assert len(diff.matched) == 1
        assert len(diff.near_misses) == 1
        assert len(diff.extra) == 1
        assert len(diff.missing) == 1
        assert diff.precision == 1 / 3
        assert diff.recall == 1 / 3


def result(
    case_id: str = "case-1",
    injector: str | None = "ArrivalDelayInjector",
    tags: list[str] | None = None,
    should_act: bool = True,
    actions: list | None = None,
    diff: ScoreDiff | None = None,
    error: str | None = None,
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        injector=injector,
        tags=tags or [],
        should_act=should_act,
        actions=actions or [],
        diff=diff,
        latency_ms=None if error else 10.0,
        error=error,
    )


def passing_result(**kwargs) -> EvalResult:
    diff = score(expect(EscalateAction()), [EscalateAction()])
    return result(actions=[EscalateAction()], diff=diff, **kwargs)


def errored_result(**kwargs) -> EvalResult:
    return result(diff=None, error="timeout", **kwargs)


class TestAggregateScores:
    def test_overall_counts_and_pass_rate(self):
        failing = result(diff=score(expect(EscalateAction()), []))
        agg = aggregate_scores([passing_result(), failing])
        assert agg.overall.cases == 2
        assert agg.overall.passed_cases == 1
        assert agg.overall.pass_rate == 0.5
        assert agg.overall.false_negatives == 1

    def test_none_injector_groups_under_clean(self):
        quiet = result(injector=None, should_act=False, diff=score(expect(), []))
        agg = aggregate_scores([quiet, passing_result()])
        assert set(agg.by_injector) == {"clean", "ArrivalDelayInjector"}
        assert agg.by_injector["clean"].cases == 1

    def test_case_appears_in_every_one_of_its_tags(self):
        agg = aggregate_scores([passing_result(tags=["underway", "direct"])])
        assert agg.by_tag["underway"].cases == 1
        assert agg.by_tag["direct"].cases == 1

    def test_errors_are_counted_per_slice(self):
        agg = aggregate_scores([passing_result(), errored_result()])
        assert agg.overall.errors == 1
        assert agg.overall.cases == 2
        # an errored case has no diff, so it can never count as passed
        assert agg.overall.passed_cases == 1

    def test_decision_matrix_excludes_errored_cases(self):
        # An errored case's empty action list is a crash, not "stayed quiet":
        # it must not appear anywhere in the matrix.
        agg = aggregate_scores(
            [
                passing_result(),  # should act, acted
                errored_result(should_act=True),
                errored_result(should_act=False),
            ]
        )
        d = agg.decisions
        assert (d.true_act, d.missed_act, d.false_alarm, d.true_quiet) == (1, 0, 0, 0)

    def test_decision_matrix_counts_wrong_actions_as_acting(self):
        # "acted" means any action at all; picking wrong actions is still acting
        wrong = result(
            should_act=True,
            actions=[notify(BOB)],
            diff=score(expect(EscalateAction()), [notify(BOB)]),
        )
        agg = aggregate_scores([wrong])
        assert agg.decisions.true_act == 1
        assert not wrong.diff.passed

    def test_false_alarm_rate(self):
        noisy = result(
            injector=None,
            should_act=False,
            actions=[EscalateAction()],
            diff=score(expect(), [EscalateAction()]),
        )
        quiet = result(injector=None, should_act=False, diff=score(expect(), []))
        agg = aggregate_scores([noisy, quiet])
        assert agg.decisions.false_alarm_rate == 0.5


class TestByActionType:
    def test_near_miss_tallies_under_expected_type(self):
        r = result(diff=score(expect(notify(ALICE)), [notify(BOB)]))
        agg = aggregate_scores([r])
        assert agg.by_action_type["notify"].near_misses == 1

    def test_type_passes_only_where_it_contributed_no_failures(self):
        # notify matched exactly, escalate went missing: same case passes for
        # notify, fails for escalate
        diff = score(expect(notify(ALICE), EscalateAction()), [notify(ALICE)])
        agg = aggregate_scores([result(diff=diff)])
        assert agg.by_action_type["notify"].passed_cases == 1
        assert agg.by_action_type["escalate"].passed_cases == 0
        assert agg.by_action_type["escalate"].false_negatives == 1

    def test_cases_counts_cases_where_type_appeared(self):
        with_notify = result(diff=score(expect(notify(ALICE)), [notify(ALICE)]))
        without_notify = passing_result()  # escalate only
        agg = aggregate_scores([with_notify, without_notify])
        assert agg.by_action_type["notify"].cases == 1
        assert agg.by_action_type["escalate"].cases == 1

    def test_errored_results_are_skipped(self):
        agg = aggregate_scores([errored_result()])
        assert agg.by_action_type == {}
