import json
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mock_server.app import Queue

from .conftest import EXAMPLES, HOTKEY, example


def call(
    base: str, path: str, body: dict | None = None, hotkey: str | None = HOTKEY
) -> tuple[int, dict | list | None]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
    if hotkey:
        request.add_header("X-Thor-Hotkey", hotkey)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


def test_loop(server: str) -> None:
    status, job = call(server, "/v1/jobs/next")
    assert status == 200 and job["job_id"] == "job_000001_fold_towel"
    assert job["deadline"] > job["issued_at"]

    status, receipt = call(server, f"/v1/jobs/{job['job_id']}/submissions", example("submission"))
    assert status == 202
    assert receipt["score"]["total"] == pytest.approx(0.95, abs=1e-3)

    status, latest = call(server, f"/v1/jobs/{job['job_id']}/submissions/latest")
    assert status == 200 and latest["submission"]["steps"][0]["caption"]["action"] == "pick up"

    status, _ = call(server, "/v1/jobs/next")
    assert status == 204, "the only job is answered, so the queue is empty for this miner"

    status, held = call(server, "/v1/validator/submissions")
    assert status == 200 and len(held) == 1 and held[0]["miner_hotkey"] == HOTKEY
    status, key = call(server, f"/v1/validator/answer-keys/{job['job_id']}")
    assert status == 200 and len(key["steps"]) == 6


def test_malformed_is_refused_with_the_field(server: str) -> None:
    call(server, "/v1/jobs/next")
    document = example("submission")
    document["steps"][1]["start_s"] = 1.0
    status, body = call(server, "/v1/jobs/job_000001_fold_towel/submissions", document)
    assert status == 400 and "steps/1/start_s" in body["error"]


def test_hotkey_must_match(server: str) -> None:
    status, body = call(server, "/v1/jobs/next", hotkey=None)
    assert status == 401
    status, body = call(
        server, "/v1/jobs/job_000001_fold_towel/submissions", example("submission"), hotkey="5" * 48
    )
    assert status == 400 and "miner_hotkey" in body["error"]


def test_late_is_accepted_and_scores_zero(late: str) -> None:
    status, job = call(late, "/v1/jobs/next")
    assert status == 200
    status, receipt = call(late, f"/v1/jobs/{job['job_id']}/submissions", example("submission"))
    assert status == 202 and receipt["score"]["total"] == 0.0 and receipt["score"]["zero_reason"] == "late"


def test_on_time_work_survives_a_late_resubmission() -> None:
    queue = Queue.from_examples(EXAMPLES, timedelta(hours=1))
    job = queue.next_job(HOTKEY)
    held, note = queue.submit(job.job_id, HOTKEY, example("submission"))
    assert note is None and held.score.total == pytest.approx(0.95, abs=1e-3)

    queue.served[(job.job_id, HOTKEY)] = replace(job, deadline=datetime.now(UTC) - timedelta(seconds=1))
    late, note = queue.submit(job.job_id, HOTKEY, example("broken_submission"))
    assert late.score.zero_reason == "late" and late.submission_id is None
    assert note == f"arrived after the deadline and was not stored; {held.submission_id} still counts"
    assert queue.held[(job.job_id, HOTKEY)] is held, "the on-time submission is the one that counts"


def test_each_miner_keeps_its_own_deadline() -> None:
    queue = Queue.from_examples(EXAMPLES, timedelta(hours=1))
    first = queue.next_job(HOTKEY)
    again = queue.next_job(HOTKEY)
    assert again.deadline == first.deadline, "fetching again does not move the deadline"
    other = queue.next_job("5" * 48)
    assert queue.served[(first.job_id, HOTKEY)].deadline == first.deadline
    assert other.deadline >= first.deadline
