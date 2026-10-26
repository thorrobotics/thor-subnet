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
import signal
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from thor.examples import examples_dir
from thor.models import AnswerKey, Job, ProtocolError, load_answer_key, load_job, load_submission, to_document
from thor.scoring import Score, score, zero

JOB_PATH = re.compile(r"^/v1/jobs/([^/]+)/submissions(?:/(latest))?$")
KEY_PATH = re.compile(r"^/v1/validator/answer-keys/([^/]+)$")


@dataclass
class Held:
    """What the queue holds for one job and one miner: the latest submission and its score."""

    submission_id: str | None
    """None for an attempt the queue did not keep (late, with on-time work already held)."""
    document: dict[str, Any]
    received_at: datetime
    score: Score | None


@dataclass
class Queue:
    """The jobs on offer, their answer keys, the copy each miner was served, and what each miner sent."""

    jobs: dict[str, Job]
    keys: dict[str, AnswerKey]
    deadline: timedelta
    served: dict[tuple[str, str], Job] = field(default_factory=dict)
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
        if not jobs:
            raise FileNotFoundError(
                f"no job*.json in {folder}; run from a checkout, set THOR_EXAMPLES_DIR or pass --examples"
            )
        return cls(jobs=jobs, keys=keys, deadline=deadline)

    def next_job(self, hotkey: str) -> Job | None:
        """The first job this miner has not answered. Its clock starts the first time it is served."""
        for job_id in self.jobs:
            if (job_id, hotkey) not in self.held:
                return self.serve(job_id, hotkey)
        return None

    def serve(self, job_id: str, hotkey: str) -> Job:
        """This miner's copy of the job, with the deadline fixed when it was first served."""
        with self.lock:
            if (job_id, hotkey) not in self.served:
                now = datetime.now(UTC)
                raw = self.jobs[job_id].raw or {}
                self.served[(job_id, hotkey)] = load_job(
                    {**raw, "issued_at": stamp(now), "deadline": stamp(now + self.deadline)}
                )
            return self.served[(job_id, hotkey)]

    def submit(self, job_id: str, hotkey: str, document: dict[str, Any]) -> tuple[Held, str | None]:
        """
        Holds the submission and scores it where an answer key exists. Lateness is judged by when
        the network received it, against the deadline this miner was given. A late submission
        never replaces one that arrived in time: the last one before the deadline counts.
        """
        job = self.serve(job_id, hotkey)
        submission = load_submission(document, job)
        key = self.keys.get(job_id)
        received_at = datetime.now(UTC)
        late = received_at > job.deadline
        result = zero("late") if late else (score(submission, key) if key else None)
        with self.lock:
            before = self.held.get((job_id, hotkey))
            keep_before = (
                late and before is not None and not (before.score and before.score.zero_reason == "late")
            )
            if keep_before:
                attempt = Held(None, to_document(submission), received_at, result)
                return (
                    attempt,
                    f"arrived after the deadline and was not stored; {before.submission_id} still counts",
                )
            self.counter += 1
            held = Held(f"sub_{self.counter:06d}", to_document(submission), received_at, result)
            self.held[(job_id, hotkey)] = held
        return held, None


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def receipt(held: Held, job_id: str, note: str | None = None) -> dict[str, Any]:
    if note is None and held.score is None:
        note = "no answer key for this job; a validator will fact check it"
    return {
        "submission_id": held.submission_id,
        "job_id": job_id,
        "received_at": stamp(held.received_at),
        "score": held.score.as_dict() if held.score else None,
        "note": note,
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
            held, note = self.queue.submit(job_id, hotkey, document)
        except ProtocolError as error:
            return self.send(HTTPStatus.BAD_REQUEST, {"error": f"malformed: {error}"})
        return self.send(HTTPStatus.ACCEPTED, receipt(held, job_id, note))


def _interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


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
        "--examples", type=Path, default=examples_dir(), help="folder of job*.json and answer_key*.json"
    )
    parser.add_argument(
        "--deadline-minutes", type=float, default=720, help="how long a miner has from fetching a job"
    )
    args = parser.parse_args()
    try:
        queue = Queue.from_examples(args.examples, timedelta(minutes=args.deadline_minutes))
    except FileNotFoundError as error:
        print(f"mock-server: {error}")
        raise SystemExit(2) from None
    try:
        server = serve(queue, port=args.port)
    except OSError as error:
        reason = error.strerror or error
        print(f"mock-server: cannot listen on port {args.port} ({reason}); stop what holds it or pass --port")
        raise SystemExit(2) from None
    print(
        f"mock-server: {len(queue.jobs)} job(s), {len(queue.keys)} answer key(s) at http://127.0.0.1:{args.port}"
    )
    print("mock-server: illustrative only; the network is not live; stop with Ctrl+C")
    # Ctrl+C (SIGINT) and a plain kill (SIGTERM) both raise KeyboardInterrupt in the serving thread, so
    # both leave the loop, close the socket and free the port. SIGINT is set explicitly because a process
    # started from a script can inherit it as ignored.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _interrupt)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.server_close()
        print("\nmock-server: stopped")
