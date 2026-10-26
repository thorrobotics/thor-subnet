"""
A local job queue, so the whole loop can run on one machine: it serves the example jobs on
the protocol's paths, accepts submissions and scores the ones it holds an answer key for.
Standard library only. Deadlines are set relative to when a job is served, so the examples
work on any day.

    thor-mock-server --port 8787

Beside the protocol's paths it offers two for a validator, which the real network serves
from THOR's own systems: every submission held, and the answer key for a job.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from thor.models import AnswerKey, Job, ProtocolError, load_answer_key, load_job, load_submission, to_document
from thor.scoring import Score, score, zero

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
JOB_PATH = re.compile(r"^/v1/jobs/([^/]+)/submissions(?:/(latest))?$")
KEY_PATH = re.compile(r"^/v1/validator/answer-keys/([^/]+)$")


@dataclass
class Held:
    """What the queue holds for one job and one miner: the latest submission and its score."""

    submission_id: str
    document: dict[str, Any]
    received_at: datetime
    score: Score | None


@dataclass
class Queue:
    """The jobs on offer, their answer keys, and what each miner has sent."""

    jobs: dict[str, Job]
    keys: dict[str, AnswerKey]
    deadline: timedelta
    held: dict[tuple[str, str], Held] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    counter: int = 0

    @classmethod
    def from_examples(cls, folder: Path, deadline: timedelta) -> Queue:
        jobs = {job.job_id: job for job in (load_job(path) for path in sorted(folder.glob("job*.json")))}
        keys = {
            key.job_id: key
            for key in (load_answer_key(path) for path in sorted(folder.glob("answer_key*.json")))
        }
        return cls(jobs=jobs, keys=keys, deadline=deadline)

    def next_job(self, hotkey: str) -> Job | None:
        """The first job this miner has not answered, with its clock started now."""
        for job_id, job in self.jobs.items():
            if (job_id, hotkey) not in self.held:
                return self.serve(job)
        return None

    def serve(self, job: Job) -> Job:
        now = datetime.now(UTC)
        document = {**(job.raw or {}), "issued_at": stamp(now), "deadline": stamp(now + self.deadline)}
        served = load_job(document)
        self.jobs[job.job_id] = served
        return served

    def submit(self, job_id: str, hotkey: str, document: dict[str, Any]) -> Held:
        """
        Holds the submission and scores it where an answer key exists. Lateness is judged by
        when the network received it, not by the time the miner wrote into it.
        """
        job = self.jobs[job_id]
        submission = load_submission(document, job)
        key = self.keys.get(job_id)
        received_at = datetime.now(UTC)
        if received_at > job.deadline:
            result: Score | None = zero("late")
        else:
            result = score(submission, key) if key else None
        with self.lock:
            self.counter += 1
            held = Held(
                submission_id=f"sub_{self.counter:06d}",
                document=to_document(submission),
                received_at=received_at,
                score=result,
            )
            self.held[(job_id, hotkey)] = held
        return held


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def receipt(held: Held, job_id: str) -> dict[str, Any]:
    return {
        "submission_id": held.submission_id,
        "job_id": job_id,
        "received_at": stamp(held.received_at),
        "score": held.score.as_dict() if held.score else None,
        "note": None if held.score else "no answer key for this job; a validator will fact check it",
    }


class Handler(BaseHTTPRequestHandler):
    queue: Queue

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (the base class's name)
        print(f"mock-server: {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    def send(self, status: HTTPStatus, body: Any = None) -> None:
        payload = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def hotkey(self) -> str | None:
        return self.headers.get("X-Thor-Hotkey")

    def do_GET(self) -> None:
        hotkey = self.hotkey()
        if self.path == "/v1/jobs/next":
            if not hotkey:
                return self.send(HTTPStatus.UNAUTHORIZED, {"error": "X-Thor-Hotkey header required"})
            job = self.queue.next_job(hotkey)
            return self.send(HTTPStatus.OK, to_document(job)) if job else self.send(HTTPStatus.NO_CONTENT)
        if match := JOB_PATH.match(self.path):
            job_id, latest = match.groups()
            if latest != "latest":
                return self.send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            held = self.queue.held.get((job_id, hotkey or ""))
            if not held:
                return self.send(HTTPStatus.NOT_FOUND, {"error": "nothing submitted for this job"})
            return self.send(HTTPStatus.OK, {**receipt(held, job_id), "submission": held.document})
        if self.path == "/v1/validator/submissions":
            return self.send(
                HTTPStatus.OK,
                [
                    {**receipt(held, job_id), "miner_hotkey": hotkey, "submission": held.document}
                    for (job_id, hotkey), held in self.queue.held.items()
                ],
            )
        if match := KEY_PATH.match(self.path):
            key = self.queue.keys.get(match.group(1))
            return (
                self.send(HTTPStatus.OK, to_document(key))
                if key
                else self.send(HTTPStatus.NOT_FOUND, {"error": "no answer key"})
            )
        return self.send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        match = JOB_PATH.match(self.path)
        if not match or match.group(2):
            return self.send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        hotkey = self.hotkey()
        if not hotkey:
            return self.send(HTTPStatus.UNAUTHORIZED, {"error": "X-Thor-Hotkey header required"})
        job_id = match.group(1)
        if job_id not in self.queue.jobs:
            return self.send(HTTPStatus.NOT_FOUND, {"error": "no such job"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            document = json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError:
            return self.send(HTTPStatus.BAD_REQUEST, {"error": "malformed: body is not JSON"})
        if isinstance(document, dict) and document.get("miner_hotkey") != hotkey:
            return self.send(
                HTTPStatus.BAD_REQUEST, {"error": "malformed: miner_hotkey does not match X-Thor-Hotkey"}
            )
        try:
            held = self.queue.submit(job_id, hotkey, document)
        except ProtocolError as error:
            return self.send(HTTPStatus.BAD_REQUEST, {"error": f"malformed: {error}"})
        return self.send(HTTPStatus.ACCEPTED, receipt(held, job_id))


def serve(queue: Queue, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    """A server bound and ready; the caller runs serve_forever on it."""
    handler = type("QueueHandler", (Handler,), {"queue": queue})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="THOR's local job queue, for trying the miner and validator loops."
    )
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--examples", type=Path, default=EXAMPLES, help="folder of job*.json and answer_key*.json"
    )
    parser.add_argument(
        "--deadline-minutes", type=float, default=720, help="how long a miner has from fetching a job"
    )
    args = parser.parse_args()
    queue = Queue.from_examples(args.examples, timedelta(minutes=args.deadline_minutes))
    server = serve(queue, port=args.port)
    print(
        f"mock-server: {len(queue.jobs)} job(s), {len(queue.keys)} answer key(s) at http://127.0.0.1:{args.port}"
    )
    print("mock-server: illustrative only; the network is not live")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
