"""M5-M7 self-check (Advanced/Expert). Run: python -m pytest -q -m student -o addopts= -k advanced
Public vectors only; the instructor grades with hidden ones."""
import copy
import math

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def stats():
    from lab9 import stats

    return stats


@pytest.mark.parametrize("n,c,k,want", [(5, 5, 5, 1.0), (5, 0, 1, 0.0), (5, 2, 1, 0.4), (10, 3, 3, 1 - 35 / 120)])
def test_pass_at_k(stats, n, c, k, want):
    assert math.isclose(stats.pass_at_k(n, c, k), want, abs_tol=1e-9)


@pytest.mark.parametrize("n,c,k,want", [(5, 5, 5, 1.0), (5, 4, 5, 0.0), (5, 4, 3, 0.4), (10, 8, 2, 28 / 45)])
def test_pass_hat_k(stats, n, c, k, want):
    assert math.isclose(stats.pass_hat_k(n, c, k), want, abs_tol=1e-9)


def test_pass_k_rejects_bad_args(stats):
    for fn in (stats.pass_at_k, stats.pass_hat_k):
        for args in [(0, 0, 1), (5, -1, 1), (5, 6, 1), (5, 2, 0), (3, 1, 4), (5, 2, 1.0)]:
            with pytest.raises(ValueError):
                fn(*args)


def _report(rows, metrics, items=4, seeds=(1, 2)):
    return {"manifest": {"eval_set_sha": "x", "items": items, "seeds": list(seeds)},
            "rows": rows, "metrics": metrics, "evaluator_failures": []}


ROWS = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["denial"] if i < 2 else []}
        for i in range(4) for s in (1, 2)]
SPEC = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                                               "threshold": {"min": 0.8}}]}


def test_integrity_flags_nan_and_dropped_rows():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    assert gate.integrity_check(base, base, SPEC) == []
    nan = _report(copy.deepcopy(ROWS), {"pass_rate": float("nan")})
    assert gate.integrity_check(nan, base, SPEC)
    dropped = _report(copy.deepcopy(ROWS[:-1]), {"pass_rate": 1.0})
    assert gate.integrity_check(dropped, base, SPEC)

    infinite = _report(copy.deepcopy(ROWS), {"pass_rate": float("inf")})
    assert gate.integrity_check(infinite, base, SPEC)


def test_integrity_flags_duplicate_pairs_and_missing_grader_scores():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    duplicate = copy.deepcopy(ROWS)
    duplicate[-1] = copy.deepcopy(duplicate[0])
    assert gate.integrity_check(_report(duplicate, {"pass_rate": 1.0}), base, SPEC)

    missing_score = copy.deepcopy(ROWS)
    missing_score[0]["pass_rate"] = None
    assert gate.integrity_check(_report(missing_score, {"pass_rate": 1.0}), base, SPEC)

    failed_evaluator = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    failed_evaluator["evaluator_failures"] = ["E-000@1:grader:error"]
    assert gate.integrity_check(failed_evaluator, base, SPEC)


def test_integrity_flags_slice_relabeling():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    relabeled = copy.deepcopy(ROWS)
    for row in relabeled:
        if row["item_id"] == "E-000":
            row["slices"] = []
    assert gate.integrity_check(_report(relabeled, {"pass_rate": 1.0}), base, SPEC)


def test_integrity_flags_loosened_spec():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    loose = copy.deepcopy(SPEC)
    loose["metrics"][0]["threshold"]["min"] = 0.5
    assert gate.integrity_check(base, base, loose, SPEC)
    assert gate.integrity_check(base, base, SPEC, SPEC) == []


def test_integrity_flags_removed_slice_and_dropped_no_significant_drop():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    base_spec = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.8,
                                    "no_significant_drop": True, "blocking": True}])
    removed = dict(SPEC, slices=[])
    assert gate.integrity_check(base, base, removed, base_spec)

    loosened = copy.deepcopy(base_spec)
    loosened["slices"][0].pop("no_significant_drop")
    assert gate.integrity_check(base, base, loosened, base_spec)


def test_slice_check_blocks_a_slice_below_floor():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    rows = copy.deepcopy(ROWS)
    for r in rows:
        if "denial" in r["slices"] and r["seed"] == 1:
            r["pass_rate"] = False
    spec = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": True}])
    blocked, _ = gate.slice_check(_report(rows, {"pass_rate": 0.75}), base, spec)
    assert blocked == ["slice:denial/pass_rate"]


def test_slice_check_blocks_significant_drop_above_floor():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    rows = copy.deepcopy(ROWS)
    for row in rows:
        if "denial" in row["slices"] and row["seed"] == 1:
            row["pass_rate"] = False
    spec = dict(SPEC, bootstrap={"n_resamples": 100, "rng": 1}, slices=[
        {"name": "denial", "metric": "pass_rate", "min": 0.4,
         "no_significant_drop": True, "blocking": True}
    ])
    blocked, lines = gate.slice_check(_report(rows, {"pass_rate": 0.75}), base, spec)
    assert blocked == ["slice:denial/pass_rate"]
    assert "CI" in lines[0]


def test_slice_check_blocks_when_slice_has_no_rows():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    spec = dict(SPEC, slices=[
        {"name": "missing", "metric": "pass_rate", "min": 0.8, "blocking": True}
    ])
    blocked, lines = gate.slice_check(base, base, spec)
    assert blocked == ["slice:missing/pass_rate"]
    assert "MISSING" in lines[0]
