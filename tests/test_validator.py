import pytest

from thor.models import load_answer_key, load_job, load_submission
from thor.scoring import score
from validator.calibration import acceptable, calibrate, key_judge, plant
from validator.vlm_check import StubBackend, fact_check
from validator.weights import weights_from_scores

from .conftest import EXAMPLES


@pytest.fixture
def key():
    return load_answer_key(EXAMPLES / "answer_key.json")


def test_planted_cases(key) -> None:
    cases = plant(key)
    assert [c.correct for c in cases] == [True, True, True, False, False, False, False]
    assert len(cases[3].steps) == len(key.steps) - 2


def test_the_key_judge_calibrates_at_one(key) -> None:
    result = calibrate(key_judge(key), plant(key))
    assert result.caught == 4 and result.passed == 3 and result.balanced_accuracy == 1.0


def test_an_over_strict_judge_is_penalised(key) -> None:
    from datetime import UTC, datetime

    from thor.models import Submission

    def exact_only(steps) -> bool:
        planted = Submission(key.job_id, "planted", datetime.now(UTC), tuple(steps))
        return score(planted, key).total == 1.0

    result = calibrate(exact_only, plant(key))
    assert result.caught == 4 and result.passed == 1 and result.balanced_accuracy == pytest.approx(2 / 3)


def test_acceptable_needs_every_part(key) -> None:
    job = load_job(EXAMPLES / "job.json")
    assert acceptable(score(load_submission(EXAMPLES / "submission.json", job), key))
    assert not acceptable(score(load_submission(EXAMPLES / "broken_submission.json", job), key))


def test_always_yes_and_always_no_score_half(key) -> None:
    cases = plant(key)
    assert calibrate(lambda steps: True, cases).balanced_accuracy == 0.5
    assert calibrate(lambda steps: False, cases).balanced_accuracy == 0.5
    stub = lambda steps: fact_check(StubBackend(), None, steps).passed  # noqa: E731
    assert calibrate(stub, cases).balanced_accuracy == 0.5


def test_weights_are_normalised_means() -> None:
    weights = weights_from_scores({"a": [0.9, 0.7], "b": [0.4], "c": []})
    assert weights == pytest.approx({"a": 2 / 3, "b": 1 / 3})
    assert weights_from_scores({"a": [0.0]}) == {"a": 0.0}


def test_correct_cases_hold_for_a_short_key() -> None:
    from thor.models import AnswerKey, Caption, Step

    key = AnswerKey(
        "job_short_000",
        "expert",
        (
            Step(0.0, 0.5, Caption("tap", "button", "right")),
            Step(0.6, 1.0, Caption("release", "button", "right")),
        ),
    )
    cases = plant(key)
    assert [c.correct for c in cases] == [True, True, False, False, False, False]
    assert calibrate(key_judge(key), cases).balanced_accuracy == 1.0
