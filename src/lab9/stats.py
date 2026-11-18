"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import bootstrap as scipy_bootstrap

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _validated_labels(human: Sequence[str], judge: Sequence[str]) -> tuple[list[str], list[str]]:
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have the same length")

    def normalize(labels: Sequence[str]) -> list[str]:
        normalized = []
        for label in labels:
            if not isinstance(label, str):
                raise ValueError("labels must be PASS or FAIL strings")
            value = label.strip().upper()
            if value not in ("PASS", POS):
                raise ValueError(f"invalid label {label!r}; expected PASS or FAIL")
            normalized.append(value)
        return normalized

    return normalize(human), normalize(judge)


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    human_labels, judge_labels = _validated_labels(human, judge)
    return {
        "tp": sum(h == POS and j == POS for h, j in zip(human_labels, judge_labels)),
        "fp": sum(h != POS and j == POS for h, j in zip(human_labels, judge_labels)),
        "fn": sum(h == POS and j != POS for h, j in zip(human_labels, judge_labels)),
        "tn": sum(h != POS and j != POS for h, j in zip(human_labels, judge_labels)),
    }


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    precision_denominator = cm["tp"] + cm["fp"]
    recall_denominator = cm["tp"] + cm["fn"]
    precision = cm["tp"] / precision_denominator if precision_denominator else 0.0
    recall = cm["tp"] / recall_denominator if recall_denominator else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = sum(cm.values())
    if not n:
        raise ValueError("kappa is undefined for empty labels")

    observed_agreement = (cm["tp"] + cm["tn"]) / n
    human_fail = cm["tp"] + cm["fn"]
    human_pass = cm["tn"] + cm["fp"]
    judge_fail = cm["tp"] + cm["fp"]
    judge_pass = cm["tn"] + cm["fn"]
    expected_agreement = (human_fail * judge_fail + human_pass * judge_pass) / (n * n)
    if expected_agreement == 1.0:
        raise ValueError("kappa is undefined when expected agreement is 1")
    return (observed_agreement - expected_agreement) / (1.0 - expected_agreement)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    rates = (observed_rate, sensitivity, specificity)
    if any(not math.isfinite(rate) or not 0.0 <= rate <= 1.0 for rate in rates):
        raise ValueError("observed rate, sensitivity, and specificity must be between 0 and 1")
    denominator = sensitivity + specificity - 1.0
    if denominator == 0.0:
        raise ValueError("Rogan-Gladen rate is undefined when sensitivity + specificity = 1")
    estimate = (observed_rate + specificity - 1.0) / denominator
    return min(1.0, max(0.0, estimate))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if len(a) == 0:
        raise ValueError("paired samples must not be empty")
    if n_resamples <= 0:
        raise ValueError("n_resamples must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")

    a_values = np.asarray(a, dtype=float)
    b_values = np.asarray(b, dtype=float)
    if not np.isfinite(a_values).all() or not np.isfinite(b_values).all():
        raise ValueError("paired samples must contain only finite values")

    difference = a_values - b_values
    delta = float(np.mean(difference))
    if np.all(difference == 0):
        return 0.0, 0.0, 0.0

    result = scipy_bootstrap(
        (a_values, b_values),
        lambda left, right: np.mean(left - right),
        paired=True,
        vectorized=False,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(rng),
    )
    return delta, float(result.confidence_interval.low), float(result.confidence_interval.high)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    # TODO M6
    raise NotImplementedError


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    # TODO M6
    raise NotImplementedError
