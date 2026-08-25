"""Conviction scoring — §10 step 5, deterministic, pure functions, no I/O
(§8.4: "A bug here is the one that costs real money"). The LLM (§5.2)
produces subscores; this module rolls them into one conviction number. It
never decides what to buy or sell — that's risk_rules.py.

§8.3's contract: "Scoring iterates the weights dict; it never hardcodes
factor names. Weights auto-normalise to 1.0 regardless of what's enabled."
So the weights dict (config, not the subscore payload) drives what gets
included — a subscore the weights dict doesn't name is silently ignored, and
a weight with no matching subscore this run is excluded from normalization
rather than treated as zero (a missing input isn't the same claim as "this
factor scored badly").

`portfolio_fit` is the one named exception (§5.2, §9): "penalty-only, applied
after roll-up". It never enters the weighted roll-up — its weight instead
scales how much it subtracts from the roll-up result afterward.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PENALTY_ONLY_FACTORS = {"portfolio_fit"}


class ScoringError(ValueError):
    pass


@dataclass
class ConvictionResult:
    score: float
    base_score: float
    normalized_weights: dict[str, float]
    contributions: dict[str, float]  # normalized_weight * subscore, per factor
    penalty: float
    missing_factors: list[str] = field(default_factory=list)

    def derivation(self) -> dict:
        """Matches §6's `conviction.derivation_json` — enough detail to
        reconstruct why a score came out the way it did."""
        return {
            "base_score": self.base_score,
            "penalty": self.penalty,
            "final_score": self.score,
            "contributions": self.contributions,
            "missing_factors": self.missing_factors,
        }


def _validate_subscores(subscores: dict[str, float]) -> None:
    for name, value in subscores.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ScoringError(f"subscore {name!r} is not numeric: {value!r}")
        if not (0 <= value <= 100):
            raise ScoringError(f"subscore {name!r}={value} out of range [0, 100]")


def _validate_weights(weights: dict[str, float]) -> None:
    for name, value in weights.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ScoringError(f"weight {name!r} is not numeric: {value!r}")
        if value < 0:
            raise ScoringError(f"weight {name!r}={value} is negative")


def normalize_weights(weights: dict[str, float], present: set[str], exclude: set[str] = frozenset()) -> dict[str, float]:
    """Weights that are excluded, zero, or have no matching entry in
    `present` don't participate; the rest are rescaled to sum to 1.0."""
    active = {name: w for name, w in weights.items() if name not in exclude and w > 0 and name in present}
    total = sum(active.values())
    if total <= 0:
        return {}
    return {name: w / total for name, w in active.items()}


def compute_conviction(subscores: dict[str, float], weights: dict[str, float]) -> ConvictionResult:
    _validate_subscores(subscores)
    _validate_weights(weights)

    present = set(subscores)
    normalized = normalize_weights(weights, present, exclude=PENALTY_ONLY_FACTORS)

    contributions = {name: w * subscores[name] for name, w in normalized.items()}
    base_score = sum(contributions.values())

    missing = sorted(
        name for name, w in weights.items() if w > 0 and name not in present and name not in PENALTY_ONLY_FACTORS
    )

    penalty = 0.0
    for name in PENALTY_ONLY_FACTORS:
        pf_weight = weights.get(name, 0.0)
        pf_subscore = subscores.get(name)
        if pf_weight > 0 and pf_subscore is not None:
            penalty += pf_weight * pf_subscore

    final_score = max(0.0, min(100.0, base_score - penalty))

    return ConvictionResult(
        score=final_score,
        base_score=base_score,
        normalized_weights=normalized,
        contributions=contributions,
        penalty=penalty,
        missing_factors=missing,
    )
