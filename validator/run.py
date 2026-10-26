"""
The validator's loop: collect what miners submitted, score each submission against its
answer key where one exists and fact check it otherwise, measure the validator's own
calibration on planted cases, and turn the scores into the weights it would set.

    thor-validator --server http://127.0.0.1:8787 --once
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from thor.client import Client, ClientError
from thor.models import AnswerKey, ProtocolError, Step, load_answer_key, load_submission
from thor.scoring import score
from validator.calibration import calibrate, key_judge, plant
from validator.vlm_check import Backend, StubBackend, fact_check
from validator.weights import set_weights, weights_from_scores

DEFAULT_SERVER = "http://127.0.0.1:8787"
VALIDATOR_HOTKEY = "5C7sX7pdVXVMGPu8ratNMTmC5gEsFrGqWJzvCNPQPya7eUAw"
"""A placeholder. The live network needs the hotkey of a registered validator."""


def collect(client: Client) -> list[dict[str, Any]]:
    """Every submission the queue holds. The live network serves a validator its share."""
    _, body = client._call("GET", "/v1/validator/submissions")
    return body or []


def answer_key(client: Client, job_id: str) -> AnswerKey | None:
    try:
        _, body = client._call("GET", f"/v1/validator/answer-keys/{job_id}")
    except ClientError as error:
        if error.status == 404:
            return None
        raise
    return load_answer_key(body)


def judge_with(backend: Backend):
    """The validator's verdict on a set of labels, for calibration: pass them when the fact check passes."""

    def judge(steps: Sequence[Step]) -> bool:
        return fact_check(backend, None, steps).passed

    return judge


def run_once(client: Client, backend: Backend | None = None, log=print) -> dict[str, float]:
    """
    One pass over everything the queue holds. Returns the weights the validator would set.
    """
    scores: dict[str, list[float]] = defaultdict(list)
    calibrations: list[float] = []
    held = collect(client)
    log(f"validator: {len(held)} submission(s) to check")
    for item in held:
        hotkey, job_id = item["miner_hotkey"], item["job_id"]
        try:
            submission = load_submission(item["submission"])
        except ProtocolError as error:
            scores[hotkey].append(0.0)
            log(f"validator: {hotkey} on {job_id}: malformed ({error}), scored 0")
            continue
        key = answer_key(client, job_id)
        if item.get("score") and item["score"].get("zero_reason") == "late":
            total, reason = 0.0, "late"
        elif key is not None:
            result = score(submission, key)
            total, reason = result.total, result.zero_reason
        else:
            check = fact_check(backend or StubBackend(), None, submission.steps)
            total = check.accepted_share if check.passed else 0.0
            reason = None if check.passed else "fact check failed"
            share = f"{check.accepted_share:.0%} of captions accepted"
            log(f"validator: {hotkey} on {job_id}: no answer key; {share}")
        scores[hotkey].append(total)
        log(f"validator: {hotkey} on {job_id}: scored {total:.4f}" + (f" ({reason})" if reason else ""))

        if key is not None:
            judge = judge_with(backend) if backend else key_judge(key)
            calibration = calibrate(judge, plant(key))
            calibrations.append(calibration.balanced_accuracy)
            caught = f"caught {calibration.caught}/{calibration.broken} broken"
            passed = f"passed {calibration.passed}/{calibration.correct} correct"
            accuracy = f"balanced accuracy {calibration.balanced_accuracy:.2f}"
            log(f"validator: calibration on {job_id}: {caught}, {passed}, {accuracy}")

    weights = weights_from_scores(scores)
    overall = sum(calibrations) / len(calibrations) if calibrations else 0.0
    return set_weights(weights, overall, log)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="THOR's validator. Illustrative; the network is not live.")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="the job queue, e.g. the mock server")
    parser.add_argument("--hotkey", default=VALIDATOR_HOTKEY, help="the validator's SS58 hotkey")
    parser.add_argument(
        "--backend", choices=["answer-key", "stub"], default="answer-key", help="the fact-check backend"
    )
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--poll-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    client = Client(args.server, args.hotkey)
    backend = StubBackend() if args.backend == "stub" else None
    print("validator: illustrative only; the network is not live")
    while True:
        try:
            run_once(client, backend)
        except ClientError as error:
            print(f"validator: the queue answered {error}", file=sys.stderr)
            if error.status == 0 and args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.poll_seconds)
