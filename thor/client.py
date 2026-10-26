"""
The job client: how a miner talks to the queue. Three calls on the protocol's paths, each
carrying the hotkey headers. Standard library only, so a miner can read the whole exchange.

Requests are not yet signed: V1 sends the hotkey and the timestamp and leaves the signature
header as "unsigned". The live network will require an sr25519 signature over
"<timestamp>\\n<body>" (see docs/protocol.md).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from thor.models import Job, Submission, load_job, to_document


class ClientError(RuntimeError):
    """The queue refused a request; the message is what it said."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


@dataclass(frozen=True)
class Client:
    base_url: str
    hotkey: str

    def next_job(self) -> Job | None:
        """One job the queue has for this miner, or None when it has nothing."""
        status, body = self._call("GET", "/v1/jobs/next")
        return load_job(body) if status == 200 and body else None

    def submit(self, submission: Submission) -> dict[str, Any]:
        """Hands in a submission; returns the queue's receipt, with a score where it had an answer key."""
        _, body = self._call("POST", f"/v1/jobs/{submission.job_id}/submissions", to_document(submission))
        return body or {}

    def latest(self, job_id: str) -> dict[str, Any] | None:
        """What the queue holds from this miner for a job, or None."""
        try:
            _, body = self._call("GET", f"/v1/jobs/{job_id}/submissions/latest")
        except ClientError as error:
            if error.status == 404:
                return None
            raise
        return body

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url.rstrip("/") + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Thor-Hotkey", self.hotkey)
        request.add_header("X-Thor-Timestamp", datetime.now(UTC).isoformat(timespec="seconds"))
        request.add_header("X-Thor-Signature", "unsigned")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                message = json.loads(raw).get("error", raw.decode())
            except (json.JSONDecodeError, AttributeError):
                message = raw.decode() or error.reason
            raise ClientError(error.code, str(message)) from None
        except urllib.error.URLError as error:
            raise ClientError(0, f"cannot reach {self.base_url}: {error.reason}") from None
