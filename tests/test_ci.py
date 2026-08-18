import pytest

from evals.scoring.results import SliceScore


def slice_score(passed: int, cases: int) -> SliceScore:
    return SliceScore(
        cases=cases,
        passed_cases=passed,
        exact_matches=0,
        near_misses=0,
        false_positives=0,
        false_negatives=0,
    )


def test_pass_rate_ci_matches_wilson_at_82_of_100():
    lo, hi = slice_score(82, 100).pass_rate_ci
    assert lo == pytest.approx(0.7333, abs=1e-3)
    assert hi == pytest.approx(0.8830, abs=1e-3)


def test_pass_rate_ci_zero_passes_starts_at_zero():
    lo, hi = slice_score(0, 4).pass_rate_ci
    assert lo == 0.0
    assert hi == pytest.approx(0.4899, abs=1e-3)


def test_pass_rate_ci_all_passes_ends_at_one():
    lo, hi = slice_score(4, 4).pass_rate_ci
    assert lo == pytest.approx(0.5101, abs=1e-3)
    assert hi == 1.0


def test_pass_rate_ci_none_when_no_cases():
    assert slice_score(0, 0).pass_rate_ci is None


def test_pass_rate_ci_serializes_as_plain_floats():
    dumped = slice_score(82, 100).model_dump(mode="json")
    lo, hi = dumped["pass_rate_ci"]
    assert isinstance(lo, float) and isinstance(hi, float)
