"""
Scores a submission against an answer key, exactly as docs/scoring.md states it: zero for
late or malformed work, otherwise steps matched by overlap, each matched pair scored on
timing and caption, and the total weighted by how well the segmentation matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from thor.models import AnswerKey, Job, ProtocolError, Step, Submission, is_late, load_submission

# The rules' constants, named as scoring.md names them.
MATCH_OVERLAP = 0.3
"""The least overlap (intersection over union) for two steps to count as the same step."""
BOUNDARY_TOLERANCE_S = 2.0
"""A boundary this far off scores nothing; closer ones score in proportion."""
CAPTION_WEIGHTS = {"action": 0.4, "object": 0.4, "hand": 0.2}
TIMING_WEIGHT = 0.5
"""The rest of a pair's score is its caption."""


@dataclass(frozen=True)
class PairScore:
    """One submitted step matched to one answer-key step."""

    submitted: int
    key: int
    overlap: float
    timing: float
    caption: float

    @property
    def score(self) -> float:
        return TIMING_WEIGHT * self.timing + (1 - TIMING_WEIGHT) * self.caption


@dataclass(frozen=True)
class Score:
    """The breakdown a miner sees: where the points went."""

    total: float
    segmentation: float
    timing: float
    caption: float
    pairs: tuple[PairScore, ...] = ()
    zero_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 4),
            "segmentation": round(self.segmentation, 4),
            "timing": round(self.timing, 4),
            "caption": round(self.caption, 4),
            "pairs": [
                {
                    "submitted": p.submitted,
                    "key": p.key,
                    "overlap": round(p.overlap, 4),
                    "timing": round(p.timing, 4),
                    "caption": round(p.caption, 4),
                }
                for p in self.pairs
            ],
            "zero_reason": self.zero_reason,
        }


ZERO = Score(total=0.0, segmentation=0.0, timing=0.0, caption=0.0)


def overlap(a: Step, b: Step) -> float:
    """Intersection over union of two steps' intervals; 0 when they do not touch."""
    intersection = max(0.0, min(a.end_s, b.end_s) - max(a.start_s, b.start_s))
    union = max(a.end_s, b.end_s) - min(a.start_s, b.start_s)
    return intersection / union if union > 0 else 0.0


def timing_score(a: Step, b: Step) -> float:
    """Each boundary scores max(0, 1 - |difference| / tolerance); the step takes the mean."""
    boundaries = ((a.start_s, b.start_s), (a.end_s, b.end_s))
    return sum(max(0.0, 1 - abs(x - y) / BOUNDARY_TOLERANCE_S) for x, y in boundaries) / len(boundaries)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def phrase_score(a: str, b: str) -> float:
    """1 for an exact match after normalising, else the Jaccard overlap of the word sets."""
    a, b = normalise(a), normalise(b)
    if a == b:
        return 1.0
    words_a, words_b = set(a.split()), set(b.split())
    union = words_a | words_b
    return len(words_a & words_b) / len(union) if union else 0.0


def caption_score(a: Step, b: Step) -> float:
    return (
        CAPTION_WEIGHTS["action"] * phrase_score(a.caption.action, b.caption.action)
        + CAPTION_WEIGHTS["object"] * phrase_score(a.caption.object, b.caption.object)
        + CAPTION_WEIGHTS["hand"] * (1.0 if a.caption.hand == b.caption.hand else 0.0)
    )


def match_steps(submitted: tuple[Step, ...], key: tuple[Step, ...]) -> list[tuple[int, int, float]]:
    """One-to-one pairs by overlap, best first, keeping only pairs at or above MATCH_OVERLAP."""
    candidates = sorted(
        ((overlap(s, k), i, j) for i, s in enumerate(submitted) for j, k in enumerate(key)),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    used_submitted: set[int] = set()
    used_key: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for value, i, j in candidates:
        if value < MATCH_OVERLAP:
            break
        if i in used_submitted or j in used_key:
            continue
        used_submitted.add(i)
        used_key.add(j)
        pairs.append((i, j, value))
    return sorted(pairs)


def score(submission: Submission, key: AnswerKey, job: Job | None = None) -> Score:
    """
    The submission's score against the answer key. Late work (which needs the job to know the
    deadline) scores zero. Everything else follows docs/scoring.md.
    """
    if job is not None and is_late(submission, job):
        return Score(**{**ZERO.__dict__, "zero_reason": "late"})
    if submission.job_id != key.job_id:
        return Score(**{**ZERO.__dict__, "zero_reason": "answer key is for another job"})

    matched = match_steps(submission.steps, key.steps)
    if not matched:
        return Score(**{**ZERO.__dict__, "zero_reason": "no step matched the answer key"})

    pairs = tuple(
        PairScore(
            submitted=i,
            key=j,
            overlap=value,
            timing=timing_score(submission.steps[i], key.steps[j]),
            caption=caption_score(submission.steps[i], key.steps[j]),
        )
        for i, j, value in matched
    )
    precision = len(pairs) / len(submission.steps)
    recall = len(pairs) / len(key.steps)
    segmentation = 2 * precision * recall / (precision + recall)
    timing = sum(p.timing for p in pairs) / len(pairs)
    caption = sum(p.caption for p in pairs) / len(pairs)
    pair_mean = sum(p.score for p in pairs) / len(pairs)
    return Score(
        total=segmentation * pair_mean, segmentation=segmentation, timing=timing, caption=caption, pairs=pairs
    )


def score_document(document: dict[str, Any], key: AnswerKey, job: Job) -> Score:
    """A raw submission document scored, with malformed ones scoring zero and the reason kept."""
    try:
        submission = load_submission(document, job)
    except ProtocolError as error:
        return Score(**{**ZERO.__dict__, "zero_reason": f"malformed: {error}"})
    return score(submission, key, job)
