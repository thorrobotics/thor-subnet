import json
from datetime import timedelta
from pathlib import Path

import pytest

from thor.models import (
    ProtocolError,
    check_against_job,
    is_late,
    load_answer_key,
    load_job,
    load_submission,
    to_document,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def test_examples_validate() -> None:
    job = load_job(EXAMPLES / "job.json")
    submission = load_submission(EXAMPLES / "submission.json", job)
    broken = load_submission(EXAMPLES / "broken_submission.json", job)
    key = load_answer_key(EXAMPLES / "answer_key.json")
    assert job.title == "Fold a towel"
    assert len(submission.steps) == 6 and len(key.steps) == 6 and len(broken.steps) == 3
    assert submission.steps[0].caption.hand == "both"
    assert not is_late(submission, job)


def test_round_trip() -> None:
    job = load_job(EXAMPLES / "job.json")
    submission = load_submission(EXAMPLES / "submission.json", job)
    assert load_submission(to_document(submission), job) == submission
    key = load_answer_key(EXAMPLES / "answer_key.json")
    assert load_answer_key(to_document(key)) == key
    assert to_document(job) == example("job")


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda d: d["steps"][0]["caption"].pop("hand"), "steps/0/caption"),
        (lambda d: d["steps"][0]["caption"].update(hand="feet"), "steps/0/caption/hand"),
        (lambda d: d["steps"][1].update(start_s=2.0), "steps/1/start_s"),
        (lambda d: d["steps"][2].update(end_s=6.9), "steps/2/end_s"),
        (lambda d: d["steps"].clear(), "steps"),
        (lambda d: d.update(extra=True), r"\(root\)"),
        (lambda d: d.update(submitted_at="yesterday"), "submitted_at"),
    ],
)
def test_bad_submissions_name_the_field(change, field) -> None:
    document = example("submission")
    change(document)
    with pytest.raises(ProtocolError, match=f"submission: {field}"):
        load_submission(document)


def test_rules_that_need_the_job() -> None:
    job = load_job(EXAMPLES / "job.json")
    document = example("submission")
    document["steps"][-1]["end_s"] = 30.0
    with pytest.raises(ProtocolError, match="steps/5/end_s: past the end of the clip"):
        load_submission(document, job)
    document = example("submission")
    document["job_id"] = "job_000002_other"
    with pytest.raises(ProtocolError, match="job_id"):
        check_against_job(load_submission(document), job)
    strict = example("job")
    strict["limits"]["max_caption_chars"] = 10
    document = example("submission")
    document["steps"][0]["caption"]["object"] = "x" * 20
    with pytest.raises(ProtocolError, match="steps/0/caption/object: over 10 characters"):
        load_submission(document, load_job(strict))


def test_late_is_a_score_not_a_rejection() -> None:
    job = load_job(EXAMPLES / "job.json")
    document = example("submission")
    document["submitted_at"] = (job.deadline + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    late = load_submission(document, job)
    assert is_late(late, job)


def test_answer_key_follows_the_step_rules() -> None:
    document = example("answer_key")
    document["steps"][3]["start_s"] = 10.0
    with pytest.raises(ProtocolError, match="answer_key: steps/3/start_s: overlaps"):
        load_answer_key(document)
