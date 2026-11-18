"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import comb

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have the same length")
    pairs = [(str(h).strip().upper(), str(j).strip().upper()) for h, j in zip(human, judge)]
    invalid = sorted({label for pair in pairs for label in pair if label not in {"PASS", "FAIL"}})
    if invalid:
        raise ValueError(f"labels must be PASS/FAIL, got {invalid}")
    return {
        "tp": sum(h == POS and j == POS for h, j in pairs),
        "fp": sum(h != POS and j == POS for h, j in pairs),
        "fn": sum(h == POS and j != POS for h, j in pairs),
        "tn": sum(h != POS and j != POS for h, j in pairs),
    }


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    predicted_positive = cm["tp"] + cm["fp"]
    actual_positive = cm["tp"] + cm["fn"]
    precision = cm["tp"] / predicted_positive if predicted_positive else 0.0
    recall = cm["tp"] / actual_positive if actual_positive else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = sum(cm.values())
    if n == 0:
        raise ValueError("kappa is undefined for an empty sample")
    p_observed = (cm["tp"] + cm["tn"]) / n
    human_fail = (cm["tp"] + cm["fn"]) / n
    judge_fail = (cm["tp"] + cm["fp"]) / n
    p_expected = human_fail * judge_fail + (1 - human_fail) * (1 - judge_fail)
    if abs(1 - p_expected) <= 1e-12:
        raise ValueError("kappa is undefined when expected agreement is 1")
    return (p_observed - p_expected) / (1 - p_expected)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    denominator = sensitivity + specificity - 1
    if abs(denominator) <= 1e-12:
        raise ValueError("Rogan-Gladen is undefined when sensitivity + specificity == 1")
    corrected = (observed_rate + specificity - 1) / denominator
    return min(1.0, max(0.0, corrected))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap

    if len(a) != len(b) or not a:
        raise ValueError("paired samples must be non-empty and have the same length")
    if n_resamples <= 0 or not 0 < confidence < 1:
        raise ValueError("n_resamples must be positive and confidence must be in (0, 1)")
    aa = np.asarray(a, dtype=float)
    bb = np.asarray(b, dtype=float)
    if not np.all(np.isfinite(aa)) or not np.all(np.isfinite(bb)):
        raise ValueError("paired samples must be finite")
    diff = aa - bb
    delta = float(np.mean(diff))
    if np.all(diff == 0):
        return 0.0, 0.0, 0.0

    def mean_difference(x, y, axis=-1):
        return np.mean(x - y, axis=axis)

    result = bootstrap(
        (aa, bb), mean_difference, paired=True, vectorized=True,
        n_resamples=n_resamples, method="percentile", confidence_level=confidence,
        rng=np.random.default_rng(rng),
    )
    return delta, float(result.confidence_interval.low), float(result.confidence_interval.high)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _validate_pass_k(n, c, k)
    return 1.0 - comb(n - c, k) / comb(n, k) if n - c >= k else 1.0


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _validate_pass_k(n, c, k)
    return comb(c, k) / comb(n, k) if c >= k else 0.0


def _validate_pass_k(n: int, c: int, k: int) -> None:
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (n, c, k)):
        raise ValueError("n, c and k must be integers")
    if n <= 0 or not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError("require n > 0, 0 <= c <= n and 1 <= k <= n")
