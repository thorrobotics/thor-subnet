import json
from datetime import timedelta
from pathlib import Path

import pytest

from thor.models import Caption, Step, load_answer_key, load_job, load_submission, to_document
from thor.scoring import (
    MATCH_OVERLAP,
    caption_score,
    match_steps,
    overlap,
    phrase_score,
    score,
    score_document,
    timing_score,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def step(start: float, end: float, action: str = "pick up", obj: str = "towel", hand: str = "both") -> Step:
    return Step(start_s=start, end_s=end, caption=Caption(action=action, object=obj, hand=hand))


@pytest.fixture
def job():
    return load_job(EXAMPLES / "job.json")


@pytest.fixture
def key():
    return load_answer_key(EXAMPLES / "answer_key.json")


def test_overlap() -> None:
    assert overlap(step(0, 10), step(0, 10)) == 1.0
    assert overlap(step(0, 10), step(5, 15)) == pytest.approx(1 / 3)
    assert overlap(step(0, 10), step(10, 20)) == 0.0


def test_timing_rewards_exact_boundaries() -> None:
    assert timing_score(step(1, 5), step(1, 5)) == 1.0
    assert timing_score(step(1, 5), step(1.5, 5)) == pytest.approx(0.875)
    assert timing_score(step(1, 5), step(3, 7)) == 0.0


def test_phrases_and_captions() -> None:
    assert phrase_score("Fold in half", "fold  in half ") == 1.0
    assert phrase_score("folded towel", "towel") == 0.5
    assert phrase_score("shirt", "towel") == 0.0
    assert caption_score(step(0, 1), step(0, 1)) == 1.0
    assert caption_score(step(0, 1, hand="left"), step(0, 1, hand="right")) == pytest.approx(0.8)
    assert caption_score(step(0, 1, obj="folded towel"), step(0, 1)) == pytest.approx(0.8)


def test_matching_is_one_to_one_and_thresholded() -> None:
    submitted = (step(0, 4), step(4, 8), step(20, 24))
    key = (step(0, 4), step(4.5, 8.5), step(9, 12))
    pairs = match_steps(submitted, key)
    assert [(i, j) for i, j, _ in pairs] == [(0, 0), (1, 1)]
    assert all(value >= MATCH_OVERLAP for _, _, value in pairs)


def test_identical_scores_one(key) -> None:
    submission = load_submission(EXAMPLES / "submission.json")
    perfect = submission.__class__(**{**submission.__dict__, "steps": key.steps})
    result = score(perfect, key)
    assert (
        result.total == 1.0 and result.segmentation == 1.0 and result.timing == 1.0 and result.caption == 1.0
    )


def test_example_scores_high(job, key) -> None:
    result = score(load_submission(EXAMPLES / "submission.json", job), key, job)
    assert len(result.pairs) == 6
    assert result.segmentation == 1.0
    assert result.total == pytest.approx(0.95, abs=1e-3)
    assert result.timing == pytest.approx(0.9333, abs=1e-3)
    assert result.caption == pytest.approx(0.9667, abs=1e-3)
    assert result.zero_reason is None


def test_broken_scores_low(job, key) -> None:
    result = score(load_submission(EXAMPLES / "broken_submission.json", job), key, job)
    assert result.total == pytest.approx(0.187, abs=1e-3)
    assert result.segmentation == pytest.approx(2 / 3)


def test_late_scores_zero(job, key) -> None:
    document = json.loads((EXAMPLES / "submission.json").read_text())
    document["submitted_at"] = (job.deadline + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    result = score(load_submission(document, job), key, job)
    assert result.total == 0.0 and result.zero_reason == "late"


def test_malformed_scores_zero(job, key) -> None:
    document = to_document(load_submission(EXAMPLES / "submission.json"))
    document["steps"][0]["caption"]["hand"] = "feet"
    result = score_document(document, key, job)
    assert (
        result.total == 0.0
        and result.zero_reason
        and result.zero_reason.startswith("malformed: submission: steps/0/caption/hand")
    )


def test_nothing_matched_scores_zero(key) -> None:
    submission = load_submission(EXAMPLES / "submission.json")
    far = submission.__class__(**{**submission.__dict__, "steps": (step(24.0, 24.5),)})
    assert score(far, key).zero_reason == "no step matched the answer key"
