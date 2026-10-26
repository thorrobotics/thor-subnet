"""
From scores to weights. Each miner's recent scores are averaged and the averages normalised
to sum to one; the validator's own standing follows its calibration. While the network is
not live nothing is set on chain: set_weights logs what it would set and returns it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def weights_from_scores(scores: Mapping[str, Sequence[float]]) -> dict[str, float]:
    """Mean score per hotkey, normalised over the miners that scored anything."""
    means = {hotkey: sum(values) / len(values) for hotkey, values in scores.items() if values}
    total = sum(means.values())
    if total <= 0:
        return dict.fromkeys(means, 0.0)
    return {hotkey: mean / total for hotkey, mean in means.items()}


def set_weights(weights: Mapping[str, float], calibration: float, log=print) -> dict[str, float]:
    """What the validator would set. The live validator signs and submits these to the chain."""
    log(f"validator: calibration {calibration:.2f}; the network is not live, so no weights are set")
    for hotkey, weight in sorted(weights.items(), key=lambda item: -item[1]):
        log(f"validator: would weight {hotkey} at {weight:.4f}")
    return dict(weights)
