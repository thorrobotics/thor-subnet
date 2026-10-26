"""
The reference miner's loop: ask the queue for a job, label it with the chosen pipeline, check
the submission against the protocol and the deadline, and hand it in. Everything a miner
would change is in miner/pipeline.py.

    thor-miner --server http://127.0.0.1:8787 --hotkey <ss58> --pipeline example --once
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from typing import Any

from miner.pipeline import BUILT_IN, Pipeline, load_pipeline
from thor.client import Client, ClientError
from thor.models import Job, ProtocolError, Submission, is_late, load_submission, to_document

DEFAULT_SERVER = "http://127.0.0.1:8787"
DEFAULT_HOTKEY = "5FQmDdKuJgkkBhY2Bd4gdBcPy79DkBaFCXtawBp1e48zuvDW"
"""A placeholder hotkey. The live network needs the hotkey of a registered miner."""


def build_submission(job: Job, steps: Any, hotkey: str, method: str | None) -> Submission:
    """The steps as a submission, checked against the protocol and the job before anything is sent."""
    draft = Submission(
        job_id=job.job_id,
        miner_hotkey=hotkey,
        submitted_at=datetime.now(UTC),
        steps=tuple(steps),
        method=method,
    )
    return load_submission(to_document(draft), job)


def run_once(
    client: Client, pipeline: Pipeline, method: str | None = None, log=print
) -> dict[str, Any] | None:
    """
    One pass: fetch, label, check, submit. Returns the queue's receipt, or None when there was
    nothing to submit (an empty queue, a pipeline still working, or work that failed a check).
    """
    job = client.next_job()
    if job is None:
        log("miner: the queue has nothing for this hotkey")
        return None
    due = job.deadline.isoformat(timespec="seconds")
    log(f"miner: job {job.job_id}: {job.title} ({job.duration_s}s), due {due}")

    steps = pipeline(job)
    if steps is None:
        log("miner: the pipeline has nothing to hand in yet; try again later")
        return None
    try:
        submission = build_submission(job, steps, client.hotkey, method)
    except ProtocolError as error:
        log(f"miner: not submitting, the work fails the protocol: {error}")
        return None
    if is_late(submission, job):
        log("miner: not submitting, the deadline has passed; it would score zero")
        return None

    receipt = client.submit(submission)
    result = receipt.get("score")
    if result:
        parts = (
            f"segmentation {result['segmentation']}, timing {result['timing']}, caption {result['caption']}"
        )
        reason = f" ({result['zero_reason']})" if result.get("zero_reason") else ""
        log(f"miner: accepted as {receipt.get('submission_id')}: score {result['total']}{reason}; {parts}")
    else:
        log(f"miner: accepted as {receipt.get('submission_id')}: {receipt.get('note') or 'no score yet'}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="THOR's reference miner. Illustrative; the network is not live."
    )
    parser.add_argument("--server", default=DEFAULT_SERVER, help="the job queue, e.g. the mock server")
    parser.add_argument("--hotkey", default=DEFAULT_HOTKEY, help="the miner's SS58 hotkey")
    parser.add_argument("--pipeline", default="example", help=f"one of {sorted(BUILT_IN)} or module:function")
    parser.add_argument(
        "--method", choices=["automated", "human", "mixed"], help="how the work is done; never scored"
    )
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--poll-seconds", type=float, default=30, help="how long to wait between passes")
    args = parser.parse_args(argv)

    try:
        pipeline = load_pipeline(args.pipeline)
    except (ValueError, ImportError, AttributeError) as error:
        print(f"miner: {error}", file=sys.stderr)
        return 2
    client = Client(args.server, args.hotkey)
    print("miner: illustrative only; the network is not live")
    while True:
        try:
            run_once(client, pipeline, args.method)
        except ClientError as error:
            print(f"miner: the queue answered {error}", file=sys.stderr)
            if error.status == 0 and args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.poll_seconds)
