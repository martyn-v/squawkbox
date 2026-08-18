from functools import cached_property
import snakemd
from pydantic import BaseModel, computed_field

from evals.scoring.results import (
    AggregateScore,
    DecisionMatrix,
    EvalResult,
    EvalRun,
    SliceScore,
)


class MetricDelta(BaseModel):
    baseline: float | None
    candidate: float | None
    baseline_ci: tuple[float, float] | None = None
    candidate_ci: tuple[float, float] | None = None

    @computed_field
    @property
    def delta(self) -> float | None:
        """Candidate minus baseline; None on either side means not comparable."""
        if self.baseline is None or self.candidate is None:
            return None
        return self.candidate - self.baseline


class SliceDelta(BaseModel):
    baseline_n: int
    candidate_n: int
    pass_rate: MetricDelta
    precision: MetricDelta
    recall: MetricDelta

    @classmethod
    def from_scores(
        cls, baseline: SliceScore | None, candidate: SliceScore | None
    ) -> SliceDelta:
        return SliceDelta(
            baseline_n=baseline.cases if baseline else 0,
            candidate_n=candidate.cases if candidate else 0,
            pass_rate=MetricDelta(
                baseline=baseline.pass_rate if baseline else None,
                candidate=candidate.pass_rate if candidate else None,
                baseline_ci=baseline.pass_rate_ci if baseline else None,
                candidate_ci=candidate.pass_rate_ci if candidate else None,
            ),
            precision=MetricDelta(
                baseline=baseline.precision if baseline else None,
                candidate=candidate.precision if candidate else None,
            ),
            recall=MetricDelta(
                baseline=baseline.recall if baseline else None,
                candidate=candidate.recall if candidate else None,
            ),
        )


class DecisionDelta(BaseModel):
    false_alarm_rate: MetricDelta
    missed_act_rate: MetricDelta

    @classmethod
    def from_matrices(
        cls, baseline: DecisionMatrix, candidate: DecisionMatrix
    ) -> DecisionDelta:
        return DecisionDelta(
            false_alarm_rate=MetricDelta(
                baseline=baseline.false_alarm_rate, candidate=candidate.false_alarm_rate
            ),
            missed_act_rate=MetricDelta(
                baseline=baseline.missed_act_rate, candidate=candidate.missed_act_rate
            ),
        )


def _slice_deltas(
    baseline: dict[str, SliceScore], candidate: dict[str, SliceScore]
) -> dict[str, SliceDelta]:
    """Pair slices by key: union of both sides, keys absent on one side included."""
    keys = dict.fromkeys([*baseline, *candidate])
    return {
        key: SliceDelta.from_scores(baseline.get(key), candidate.get(key))
        for key in keys
    }


class AggregateDelta(BaseModel):
    overall: SliceDelta
    decisions: DecisionDelta
    by_injector: dict[str, SliceDelta]
    by_tag: dict[str, SliceDelta]
    by_action_type: dict[str, SliceDelta]

    @classmethod
    def from_summary(
        cls, baseline: AggregateScore, candidate: AggregateScore
    ) -> AggregateDelta:
        return AggregateDelta(
            overall=SliceDelta.from_scores(baseline.overall, candidate.overall),
            decisions=DecisionDelta.from_matrices(
                baseline.decisions, candidate.decisions
            ),
            by_injector=_slice_deltas(baseline.by_injector, candidate.by_injector),
            by_tag=_slice_deltas(baseline.by_tag, candidate.by_tag),
            by_action_type=_slice_deltas(
                baseline.by_action_type, candidate.by_action_type
            ),
        )


class RegressedCase(BaseModel):
    case_id: str
    reasons: list[str]


class CaseFlips(BaseModel):
    """Per-case outcome changes between two runs, joined on case_id."""

    fixed: list[str]  # fail → pass
    regressed: list[RegressedCase]  # pass → fail, with why
    still_failing: list[str]
    only_baseline: list[str]
    only_candidate: list[str]

    @classmethod
    def from_results(
        cls, baseline: list[EvalResult], candidate: list[EvalResult]
    ) -> CaseFlips:
        b = {r.case_id: r for r in baseline}
        c = {r.case_id: r for r in candidate}

        fixed, regressed, still_failing = [], [], []
        for case_id in (k for k in b if k in c):
            b_passed, c_passed = _passed(b[case_id]), _passed(c[case_id])
            if not b_passed and c_passed:
                fixed.append(case_id)
            elif b_passed and not c_passed:
                regressed.append(
                    RegressedCase(
                        case_id=case_id, reasons=_failure_reasons(c[case_id])
                    )
                )
            elif not b_passed and not c_passed:
                still_failing.append(case_id)

        return cls(
            fixed=fixed,
            regressed=regressed,
            still_failing=still_failing,
            only_baseline=[k for k in b if k not in c],
            only_candidate=[k for k in c if k not in b],
        )


def _passed(result: EvalResult) -> bool:
    return result.diff is not None and result.diff.passed


def _failure_reasons(result: EvalResult) -> list[str]:
    if result.error is not None:
        return [f"error: {result.error}"]
    if result.diff is None:
        return []
    reasons = [reason for nm in result.diff.near_misses for reason in nm.reasons]
    reasons += [f"extra {action.type}" for action in result.diff.extra]
    reasons += [f"missing {action.type}" for action in result.diff.missing]
    return reasons


class RunComparison(BaseModel):
    run_a: EvalRun
    run_b: EvalRun

    @property
    def baseline(self) -> EvalRun:
        """Older run: the reference the candidate is measured against."""
        return self.run_a if self.run_a.run_at <= self.run_b.run_at else self.run_b

    @property
    def candidate(self) -> EvalRun:
        return self.run_b if self.baseline is self.run_a else self.run_a

    @property
    def like_for_like(self) -> bool:
        """Same dataset on both sides; deltas and flips are only meaningful then."""
        return self.run_a.cases_hash == self.run_b.cases_hash

    @computed_field
    @cached_property
    def summary(self) -> AggregateDelta:
        return AggregateDelta.from_summary(
            self.baseline.summary, self.candidate.summary
        )

    @computed_field
    @cached_property
    def flips(self) -> CaseFlips:
        return CaseFlips.from_results(self.baseline.results, self.candidate.results)


def _validate(comparison: RunComparison):
    if comparison.run_a.cases_hash != comparison.run_b.cases_hash:
        raise ValueError(
            "Case file hashes do not match, cannot compare runs (use --force to compare anyway)"
        )


def render_comparison(comparison: RunComparison) -> str:
    doc = snakemd.new_doc()
    render_header(doc, comparison)
    if not comparison.like_for_like:
        doc.add_paragraph(
            "⚠ Case file hashes differ: deltas are not like-for-like "
            "and case flips are omitted."
        )
    render_summary(doc, comparison)
    if comparison.like_for_like:
        render_flips(doc, comparison)
    return str(doc)


def render_header(doc: snakemd.Document, comparison: RunComparison) -> None:
    """Markdown table of what was tested on each side, differing rows flagged."""
    b, c = comparison.baseline, comparison.candidate
    rows = [
        ("run_at", b.run_at, c.run_at),
        ("model", b.model, c.model),
        ("temperature", b.model_temperature, c.model_temperature),
        ("label", b.label, c.label),
        ("git_sha", b.git_sha, c.git_sha),
        ("prompt_hash", b.system_prompt_hash, c.system_prompt_hash),
    ]
    data = [
        # run_at always differs — it's the ordering key, not a change worth flagging
        [
            name,
            _cell(b_val),
            _cell(c_val),
            "≠" if b_val != c_val and name != "run_at" else "",
        ]
        for name, b_val, c_val in rows
    ]

    doc.add_heading("Run comparison")
    doc.add_table(["", "baseline", "candidate", ""], data)


def render_summary(doc: snakemd.Document, comparison: RunComparison) -> None:
    doc.add_heading("Summary comparison")

    data = [_slice_row("**overall**", comparison.summary.overall)]
    slices = {
        "injector": comparison.summary.by_injector,
        "tag": comparison.summary.by_tag,
        "action type": comparison.summary.by_action_type,
    }
    for slice_name, slice_dict in slices.items():
        data.append([f"**{slice_name}**", "", "", "", ""])
        data += [_slice_row(key, s) for key, s in slice_dict.items()]

    doc.add_table(["slice", "n", "pass rate", "precision", "recall"], data)

    decisions = comparison.summary.decisions
    doc.add_table(
        ["decision", "rate"],
        [
            ["false alarm", _metric_cell(decisions.false_alarm_rate)],
            ["missed act", _metric_cell(decisions.missed_act_rate)],
        ],
    )


def render_flips(doc: snakemd.Document, comparison: RunComparison) -> None:
    flips = comparison.flips
    doc.add_heading("Case flips")

    if flips.regressed:
        doc.add_paragraph(f"Regressed ({len(flips.regressed)}):")
        doc.add_unordered_list(
            [f"`{r.case_id}` — {'; '.join(r.reasons)}" for r in flips.regressed]
        )
    if flips.fixed:
        doc.add_paragraph(f"Fixed ({len(flips.fixed)}): " + ", ".join(flips.fixed))
    if flips.still_failing:
        doc.add_paragraph(
            f"Still failing ({len(flips.still_failing)}): "
            + ", ".join(flips.still_failing)
        )
    if flips.only_baseline:
        doc.add_paragraph("Only in baseline: " + ", ".join(flips.only_baseline))
    if flips.only_candidate:
        doc.add_paragraph("Only in candidate: " + ", ".join(flips.only_candidate))
    if not (flips.regressed or flips.fixed or flips.still_failing):
        doc.add_paragraph("No flips: every case kept its outcome.")


def _slice_row(name: str, s: SliceDelta) -> list[str]:
    return [
        name,
        _n_cell(s),
        _metric_cell(s.pass_rate),
        _metric_cell(s.precision),
        _metric_cell(s.recall),
    ]


def _n_cell(s: SliceDelta) -> str:
    if s.baseline_n == s.candidate_n:
        return str(s.baseline_n)
    return f"{s.baseline_n} → {s.candidate_n}"


def _metric_cell(m: MetricDelta) -> str:
    """baseline → candidate (Δ); an uncomputable side renders as —.
    Sides carrying a confidence interval render it as [lo, hi] after the value."""
    if m.baseline is None and m.candidate is None:
        return "—"
    baseline = _value_with_ci(m.baseline, m.baseline_ci)
    candidate = _value_with_ci(m.candidate, m.candidate_ci)
    # explicit sign so regressions stand out scanning down the column
    delta = "" if m.delta is None else f" ({m.delta:+.2f})"
    return f"{baseline} → {candidate}{delta}"


def _value_with_ci(value: float | None, ci: tuple[float, float] | None) -> str:
    if value is None:
        return "—"
    if ci is None:
        return f"{value:.2f}"
    # ±half-width for scanability; Wilson is asymmetric, so this is approximate —
    # the exact [lo, hi] stays in the report JSON
    return f"{value:.2f} ±{(ci[1] - ci[0]) / 2:.2f}"


def _cell(value: object) -> str:
    if value is None:
        return "—"
    text = str(value)
    # full sha256/git hashes wreck table alignment; 12 hex chars still identify
    head, dirty = (text[:-6], "-dirty") if text.endswith("-dirty") else (text, "")
    if len(head) > 12 and all(ch in "0123456789abcdef" for ch in head):
        head = head[:12]
    return head + dirty


def _load_eval_run(file: str) -> EvalRun:
    with open(file, "r") as f:
        return EvalRun.model_validate_json(f.read())


def compare(
    run_file_a: str, run_file_b: str, force: bool = False, output: str | None = None
) -> None:
    comparison = RunComparison(
        run_a=_load_eval_run(run_file_a), run_b=_load_eval_run(run_file_b)
    )

    if not force:
        _validate(comparison)

    text = render_comparison(comparison)
    if output:
        with open(output, "w") as f:
            f.write(text)

    from rich.console import Console
    from rich.markdown import Markdown

    Console().print(Markdown(text))
