import pytest

from evals.scoring.compare import (
    AggregateDelta,
    CaseFlips,
    DecisionDelta,
    MetricDelta,
    RunComparison,
    SliceDelta,
    _slice_deltas,
    _validate,
    render_comparison,
)
from evals.scoring.results import (
    AggregateScore,
    DecisionMatrix,
    EvalResult,
    EvalRun,
    NearMiss,
    ScoreDiff,
    SliceScore,
)
from squawkbox.models import EscalateAction, NotifyAction


def matrix(
    true_act: int = 0, missed_act: int = 0, false_alarm: int = 0, true_quiet: int = 0
) -> DecisionMatrix:
    return DecisionMatrix(
        true_act=true_act,
        missed_act=missed_act,
        false_alarm=false_alarm,
        true_quiet=true_quiet,
    )


def aggregate(decisions: DecisionMatrix) -> AggregateScore:
    empty = SliceScore(
        cases=0,
        passed_cases=0,
        exact_matches=0,
        near_misses=0,
        false_positives=0,
        false_negatives=0,
    )
    return AggregateScore(
        overall=empty, decisions=decisions, by_injector={}, by_tag={}, by_action_type={}
    )


def eval_run(
    summary: AggregateScore,
    run_at: str,
    results: list[EvalResult] | None = None,
    cases_hash: str = "sha256:samehash",
) -> EvalRun:
    return EvalRun(
        model="test-model",
        model_temperature=0.0,
        system_prompt_hash="prompthash",
        git_sha="abc123",
        cases_path="cases.json",
        cases_meta=None,
        cases_hash=cases_hash,
        run_at=run_at,
        complete=True,
        summary=summary,
        results=results or [],
    )


def passing(case_id: str) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        actions=[],
        diff=ScoreDiff(passed=True, matched=[], near_misses=[], extra=[], missing=[]),
        latency_ms=None,
    )


def failing(
    case_id: str,
    near_misses: list[NearMiss] | None = None,
    extra: list | None = None,
    missing: list | None = None,
) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        actions=[],
        diff=ScoreDiff(
            passed=False,
            matched=[],
            near_misses=near_misses or [],
            extra=extra or [],
            missing=missing or [],
        ),
        latency_ms=None,
    )


def errored(case_id: str, error: str = "model returned invalid JSON") -> EvalResult:
    return EvalResult(
        case_id=case_id, actions=[], error=error, diff=None, latency_ms=None
    )


def slice_score(
    cases: int = 4,
    passed_cases: int = 2,
    exact_matches: int = 2,
    near_misses: int = 1,
    false_positives: int = 1,
    false_negatives: int = 1,
) -> SliceScore:
    return SliceScore(
        cases=cases,
        passed_cases=passed_cases,
        exact_matches=exact_matches,
        near_misses=near_misses,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


class TestMetricDelta:
    def test_delta_is_candidate_minus_baseline(self):
        assert MetricDelta(baseline=0.25, candidate=0.75).delta == 0.5

    def test_delta_none_when_either_side_missing(self):
        assert MetricDelta(baseline=None, candidate=0.75).delta is None
        assert MetricDelta(baseline=0.25, candidate=None).delta is None


class TestSliceDelta:
    def test_from_scores_pairs_all_metrics(self):
        d = SliceDelta.from_scores(
            slice_score(cases=4, passed_cases=2), slice_score(cases=4, passed_cases=3)
        )
        assert d.baseline_n == 4
        assert d.candidate_n == 4
        assert d.pass_rate.baseline == 0.5
        assert d.pass_rate.candidate == 0.75
        assert d.pass_rate.delta == 0.25

    def test_missing_side_yields_zero_n_and_none_metrics(self):
        d = SliceDelta.from_scores(None, slice_score())
        assert d.baseline_n == 0
        assert d.pass_rate.baseline is None
        assert d.pass_rate.delta is None


class TestSliceDeltas:
    def test_union_keeps_baseline_order_then_candidate_extras(self):
        deltas = _slice_deltas(
            {"shared": slice_score(), "base_only": slice_score()},
            {"cand_only": slice_score(), "shared": slice_score()},
        )
        assert list(deltas) == ["shared", "base_only", "cand_only"]
        assert deltas["base_only"].candidate_n == 0
        assert deltas["cand_only"].baseline_n == 0


class TestBaselineOrdering:
    def test_older_run_is_baseline_regardless_of_argument_order(self):
        older = eval_run(aggregate(matrix()), "2026-08-01T00:00:00+00:00")
        newer = eval_run(aggregate(matrix()), "2026-08-02T00:00:00+00:00")
        assert RunComparison(run_a=newer, run_b=older).baseline is older
        assert RunComparison(run_a=older, run_b=newer).baseline is older


class TestValidate:
    def test_rejects_differing_cases_hash(self):
        comparison = RunComparison(
            run_a=eval_run(
                aggregate(matrix()), "2026-08-01T00:00:00+00:00", cases_hash="sha256:aaa"
            ),
            run_b=eval_run(
                aggregate(matrix()), "2026-08-02T00:00:00+00:00", cases_hash="sha256:bbb"
            ),
        )
        with pytest.raises(ValueError, match="do not match"):
            _validate(comparison)


class TestDecisionDelta:
    def test_compares_rates_between_matrices(self):
        d = DecisionDelta.from_matrices(
            matrix(true_act=3, missed_act=1, false_alarm=1, true_quiet=3),
            matrix(true_act=4, missed_act=0, false_alarm=2, true_quiet=2),
        )
        assert d.false_alarm_rate.baseline == 0.25
        assert d.false_alarm_rate.candidate == 0.5
        assert d.false_alarm_rate.delta == 0.25
        assert d.missed_act_rate.baseline == 0.25
        assert d.missed_act_rate.candidate == 0.0
        assert d.missed_act_rate.delta == -0.25

    def test_undefined_rate_yields_none_sides_and_delta(self):
        # baseline has no should-stay-quiet cases: false_alarm_rate is undefined
        d = DecisionDelta.from_matrices(
            matrix(true_act=1),
            matrix(true_act=1, false_alarm=1, true_quiet=1),
        )
        assert d.false_alarm_rate.baseline is None
        assert d.false_alarm_rate.candidate == 0.5
        assert d.false_alarm_rate.delta is None


class TestFromSummary:
    def test_builds_decisions_from_both_sides(self):
        agg = AggregateDelta.from_summary(
            aggregate(matrix(true_act=2, missed_act=2, false_alarm=1, true_quiet=3)),
            aggregate(matrix(true_act=4, missed_act=0, false_alarm=1, true_quiet=3)),
        )
        assert agg.decisions.missed_act_rate.baseline == 0.5
        assert agg.decisions.missed_act_rate.candidate == 0.0
        assert agg.decisions.missed_act_rate.delta == -0.5


class TestCaseFlips:
    def test_classifies_fixed_regressed_still_failing(self):
        flips = CaseFlips.from_results(
            baseline=[passing("a"), failing("b"), failing("c")],
            candidate=[failing("a"), passing("b"), failing("c")],
        )
        assert [f.case_id for f in flips.regressed] == ["a"]
        assert flips.fixed == ["b"]
        assert flips.still_failing == ["c"]

    def test_unchanged_passing_cases_are_not_flips(self):
        flips = CaseFlips.from_results(
            baseline=[passing("a")], candidate=[passing("a")]
        )
        assert not flips.fixed
        assert not flips.regressed
        assert not flips.still_failing

    def test_cases_present_in_only_one_run(self):
        flips = CaseFlips.from_results(
            baseline=[passing("a"), passing("old")],
            candidate=[passing("a"), passing("new")],
        )
        assert flips.only_baseline == ["old"]
        assert flips.only_candidate == ["new"]

    def test_regression_carries_diff_reasons(self):
        near = NearMiss(
            expected=NotifyAction(recipients=[]),
            actual=NotifyAction(recipients=[]),
            reasons=["recipients mismatch"],
        )
        flips = CaseFlips.from_results(
            baseline=[passing("a"), passing("b")],
            candidate=[
                failing("a", near_misses=[near], missing=[EscalateAction()]),
                errored("b"),
            ],
        )
        assert flips.regressed[0].reasons == [
            "recipients mismatch",
            "missing escalate",
        ]
        assert flips.regressed[1].reasons == ["error: model returned invalid JSON"]

    def test_error_counts_as_failure(self):
        flips = CaseFlips.from_results(
            baseline=[errored("a")], candidate=[passing("a")]
        )
        assert flips.fixed == ["a"]


class TestRenderFlips:
    def test_rendered_comparison_lists_flips_with_reasons(self):
        base = aggregate(matrix(true_act=1))
        comparison = RunComparison(
            run_a=eval_run(
                base,
                "2026-08-01T00:00:00+00:00",
                results=[passing("case-1"), failing("case-2")],
            ),
            run_b=eval_run(
                base,
                "2026-08-02T00:00:00+00:00",
                results=[
                    failing("case-1", missing=[EscalateAction()]),
                    passing("case-2"),
                ],
            ),
        )
        text = render_comparison(comparison)
        assert "Case flips" in text
        assert "case-1" in text
        assert "missing escalate" in text
        assert "case-2" in text


class TestNotLikeForLike:
    def test_differing_cases_hash_skips_flips_and_flags_deltas(self):
        base = aggregate(matrix(true_act=1))
        comparison = RunComparison(
            run_a=eval_run(
                base,
                "2026-08-01T00:00:00+00:00",
                results=[passing("case-1")],
                cases_hash="sha256:aaa",
            ),
            run_b=eval_run(
                base,
                "2026-08-02T00:00:00+00:00",
                results=[failing("case-1")],
                cases_hash="sha256:bbb",
            ),
        )
        assert not comparison.like_for_like
        text = render_comparison(comparison)
        assert "not like-for-like" in text
        assert "Case flips" not in text


class TestRenderDecisions:
    def test_rendered_comparison_shows_decision_rates(self):
        comparison = RunComparison(
            run_a=eval_run(
                aggregate(matrix(true_act=3, missed_act=1, false_alarm=1, true_quiet=3)),
                run_at="2026-08-01T00:00:00+00:00",
            ),
            run_b=eval_run(
                aggregate(matrix(true_act=4, missed_act=0, false_alarm=2, true_quiet=2)),
                run_at="2026-08-02T00:00:00+00:00",
            ),
        )
        text = render_comparison(comparison)
        assert "false alarm" in text
        assert "missed act" in text
        assert "0.25 → 0.50 (+0.25)" in text  # false alarm worsened
        assert "0.25 → 0.00 (-0.25)" in text  # missed act improved


class TestPassRateCI:
    def scores(self) -> tuple[SliceScore, SliceScore]:
        def s(passed: int) -> SliceScore:
            return SliceScore(
                cases=100,
                passed_cases=passed,
                exact_matches=0,
                near_misses=0,
                false_positives=0,
                false_negatives=0,
            )

        return s(82), s(90)

    def test_slice_delta_carries_pass_rate_cis(self):
        baseline, candidate = self.scores()
        delta = SliceDelta.from_scores(baseline, candidate)
        lo, hi = delta.pass_rate.baseline_ci
        assert lo == pytest.approx(0.7333, abs=1e-3)
        assert hi == pytest.approx(0.8830, abs=1e-3)
        assert delta.pass_rate.candidate_ci is not None

    def test_missing_side_has_no_ci(self):
        _, candidate = self.scores()
        delta = SliceDelta.from_scores(None, candidate)
        assert delta.pass_rate.baseline_ci is None

    def test_rendered_pass_rate_cell_shows_intervals(self):
        from evals.scoring.compare import _metric_cell

        baseline, candidate = self.scores()
        delta = SliceDelta.from_scores(baseline, candidate)
        cell = _metric_cell(delta.pass_rate)
        assert cell == "0.82 ±0.07 → 0.90 ±0.06 (+0.08)"

    def test_rendered_cell_without_ci_is_unchanged(self):
        cell = MetricDelta(baseline=0.5, candidate=0.75)
        from evals.scoring.compare import _metric_cell

        assert _metric_cell(cell) == "0.50 → 0.75 (+0.25)"
