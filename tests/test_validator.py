from datetime import timedelta
from pathlib import Path

import pytest

from miner.pipeline import load_pipeline
from miner.run import run_once as mine_once
from thor.client import Client
from thor.models import load_answer_key, load_job, load_submission
from thor.scoring import score
from validator.calibration import acceptable, calibrate, key_judge, plant
from validator.run import run_once as validate_once
from validator.vlm_check import StubBackend, fact_check
from validator.weights import weights_from_scores

from .test_mock_server import HOTKEY, running

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
server = pytest.fixture(lambda: (yield from running(timedelta(hours=1))))


@pytest.fixture
def key():
    return load_answer_key(EXAMPLES / "answer_key.json")


def test_planted_cases(key) -> None:
    cases = plant(key)
    assert [c.correct for c in cases] == [True, False, False, False, False]
    assert len(cases[1].steps) == len(key.steps) - 2


def test_the_key_judge_calibrates_at_one(key) -> None:
    result = calibrate(key_judge(key), plant(key))
    assert result.caught == 4 and result.passed == 1 and result.balanced_accuracy == 1.0


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


def test_miner_then_validator(server: str) -> None:
    assert mine_once(Client(server, HOTKEY), load_pipeline("example"), log=lambda line: None)
    lines: list[str] = []
    weights = validate_once(Client(server, "validator"), log=lines.append)
    assert weights == {HOTKEY: 1.0}
    assert any("scored 0.9500" in line for line in lines)
    assert any("balanced accuracy 1.00" in line for line in lines)
    assert lines[-2].endswith("no weights are set") or any("no weights are set" in line for line in lines)
