"""
Scoring the validator: planted cases whose truth the network knows, and the balanced accuracy
of the validator's judgements over them. Correct labels are an answer key's own steps; broken
ones are those steps with a third of them dropped, every boundary moved past the tolerance,
every hand swapped or every object changed; two more correct cases carry the small
imperfections real work has, boundaries a few tenths off and one object phrased differently,
so a judge that is too strict is caught as surely as one that is too lenient. The validator
does not know which is which, and a judge that always says yes or always says no lands on
0.5, the same as guessing.

Where the validator holds the answer key it judges with the scorer, and a set of labels
passes only when its segmentation, timing and captions are each acceptable on their own:
that is what "how close the steps, timings and captions are" means in practice.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from thor.models import AnswerKey, Step, Submission
from thor.scoring import BOUNDARY_TOLERANCE_S, Score, score

ACCEPTABLE = {"segmentation": 0.9, "timing": 0.75, "caption": 0.9}
"""The least each part of a score may be for the labels to pass."""


@dataclass(frozen=True)
class Planted:
    steps: tuple[Step, ...]
    correct: bool
    description: str


def plant(key: AnswerKey) -> tuple[Planted, ...]:
    """Correct cases, one exact and up to two imperfect, and four broken ones from an answer key."""
    steps = key.steps
    shift = BOUNDARY_TOLERANCE_S + 1
    swapped = {"left": "right", "right": "left", "both": "left"}
    dropped = max(1, len(steps) // 3)

    def jitter(step: Step) -> float:
        """A tenth of the step, at most a fifth of the tolerance: still overlapping, still inside the bar."""
        return min(BOUNDARY_TOLERANCE_S / 5, step.duration_s / 10)

    correct = [
        Planted(steps, True, "the answer key's own steps"),
        Planted(
            tuple(replace(s, start_s=s.start_s + jitter(s), end_s=s.end_s + jitter(s)) for s in steps),
            True,
            "every boundary a little off, inside the tolerance",
        ),
    ]
    if len(steps) >= 3:
        rephrased = list(steps)
        last = steps[-1]
        rephrased[-1] = replace(last, caption=replace(last.caption, object=f"the {last.caption.object}"))
        correct.append(Planted(tuple(rephrased), True, "one object phrased differently"))
    return (
        *correct,
        Planted(steps[dropped:], False, f"the first {dropped} step(s) dropped"),
        Planted(
            tuple(replace(s, start_s=s.start_s + shift, end_s=s.end_s + shift) for s in steps),
            False,
            "every boundary moved past the tolerance",
        ),
        Planted(
            tuple(replace(s, caption=replace(s.caption, hand=swapped[s.caption.hand])) for s in steps),
            False,
            "every hand swapped",
        ),
        Planted(
            tuple(replace(s, caption=replace(s.caption, object="something else")) for s in steps),
            False,
            "every object changed",
        ),
    )


Judge = Callable[[Sequence[Step]], bool]
"""The validator's verdict on a set of labels: True to pass them, False to reject them."""


def acceptable(result: Score) -> bool:
    """Whether every part of a score clears its bar."""
    return all(getattr(result, part) >= floor for part, floor in ACCEPTABLE.items())


def key_judge(key: AnswerKey) -> Judge:
    """The judge a validator uses when it holds the answer key: score the labels, then apply the bars."""

    def judge(steps: Sequence[Step]) -> bool:
        planted = Submission(key.job_id, "planted", datetime.now(UTC), tuple(steps))
        return acceptable(score(planted, key))

    return judge


@dataclass(frozen=True)
class Calibration:
    caught: int
    broken: int
    passed: int
    correct: int

    @property
    def balanced_accuracy(self) -> float:
        """The mean of the share of broken labels caught and the share of correct labels passed."""
        catch_rate = self.caught / self.broken if self.broken else 0.0
        pass_rate = self.passed / self.correct if self.correct else 0.0
        return (catch_rate + pass_rate) / 2


def calibrate(judge: Judge, cases: Sequence[Planted]) -> Calibration:
    broken = [c for c in cases if not c.correct]
    correct = [c for c in cases if c.correct]
    return Calibration(
        caught=sum(not judge(c.steps) for c in broken),
        broken=len(broken),
        passed=sum(judge(c.steps) for c in correct),
        correct=len(correct),
    )
