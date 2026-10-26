"""
The protocol's three documents as typed values: a job, a submission and an answer key. Each
loads from JSON, is checked against its schema (thor/schemas) and then against the rules the
schema cannot express: steps in time order, no overlap, inside the clip, under the job's
limits, and the submission on time. A document that fails any check raises ProtocolError
naming the field, so a miner finds out before the network does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

Hand = Literal["left", "right", "both"]


class ProtocolError(ValueError):
    """A document that does not follow the protocol. The message names the offending field."""


@dataclass(frozen=True)
class Caption:
    action: str
    object: str
    hand: Hand


@dataclass(frozen=True)
class Step:
    start_s: float
    end_s: float
    caption: Caption

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Job:
    job_id: str
    video_url: str
    duration_s: float
    title: str
    instructions: str
    issued_at: datetime
    deadline: datetime
    max_steps: int = 50
    max_caption_chars: int = 80
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class Submission:
    job_id: str
    miner_hotkey: str
    submitted_at: datetime
    steps: tuple[Step, ...]
    method: str | None = None


@dataclass(frozen=True)
class AnswerKey:
    job_id: str
    provenance: str
    steps: tuple[Step, ...]


# --- schema validation ---------------------------------------------------------------------

_SCHEMAS = ("job", "submission", "answer_key")


def _schema(name: str) -> dict[str, Any]:
    return json.loads(resources.files("thor.schemas").joinpath(f"{name}.schema.json").read_text())


def _registry() -> Registry:
    """The three schemas, so the answer key can reuse the submission's step definition."""
    registry: Registry = Registry()
    for name in _SCHEMAS:
        schema = _schema(name)
        registry = registry.with_resource(f"{name}.schema.json", Resource.from_contents(schema))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


_REGISTRY = _registry()


def _validate(name: str, document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ProtocolError(f"{name}: expected an object, got {type(document).__name__}")
    validator = Draft202012Validator(_schema(name), registry=_REGISTRY)
    errors = sorted(validator.iter_errors(document), key=lambda e: e.path)
    error: ValidationError | None = errors[0] if errors else None
    if error is not None:
        field = "/".join(str(part) for part in error.absolute_path) or "(root)"
        raise ProtocolError(f"{name}: {field}: {error.message}")
    return document


def _parse_time(name: str, field: str, value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProtocolError(f"{name}: {field}: not an ISO 8601 timestamp") from error
    if moment.tzinfo is None:
        raise ProtocolError(f"{name}: {field}: timestamp needs a timezone")
    return moment


def _steps(name: str, items: list[dict[str, Any]]) -> tuple[Step, ...]:
    steps = tuple(
        Step(
            start_s=float(item["start_s"]),
            end_s=float(item["end_s"]),
            caption=Caption(
                action=item["caption"]["action"],
                object=item["caption"]["object"],
                hand=item["caption"]["hand"],
            ),
        )
        for item in items
    )
    for index, step in enumerate(steps):
        if step.end_s <= step.start_s:
            raise ProtocolError(f"{name}: steps/{index}/end_s: must be after start_s")
        if index > 0 and step.start_s < steps[index - 1].end_s:
            raise ProtocolError(f"{name}: steps/{index}/start_s: overlaps the previous step")
    return steps


# --- loading -------------------------------------------------------------------------------


def _read(source: str | Path | dict[str, Any]) -> Any:
    if isinstance(source, dict):
        return source
    return json.loads(Path(source).read_text())


def load_job(source: str | Path | dict[str, Any]) -> Job:
    """A job from a path or a parsed document, checked against the job schema."""
    document = _validate("job", _read(source))
    limits = document.get("limits", {})
    return Job(
        job_id=document["job_id"],
        video_url=document["video"]["url"],
        duration_s=float(document["video"]["duration_s"]),
        title=document["task"]["title"],
        instructions=document["task"]["instructions"],
        issued_at=_parse_time("job", "issued_at", document["issued_at"]),
        deadline=_parse_time("job", "deadline", document["deadline"]),
        max_steps=int(limits.get("max_steps", 50)),
        max_caption_chars=int(limits.get("max_caption_chars", 80)),
        raw=document,
    )


def load_submission(source: str | Path | dict[str, Any], job: Job | None = None) -> Submission:
    """A submission, checked against its schema and, given its job, against the job's clip and limits."""
    document = _validate("submission", _read(source))
    submission = Submission(
        job_id=document["job_id"],
        miner_hotkey=document["miner_hotkey"],
        submitted_at=_parse_time("submission", "submitted_at", document["submitted_at"]),
        steps=_steps("submission", document["steps"]),
        method=document.get("method"),
    )
    if job is not None:
        check_against_job(submission, job)
    return submission


def load_answer_key(source: str | Path | dict[str, Any]) -> AnswerKey:
    """An answer key, checked against its schema and the step rules."""
    document = _validate("answer_key", _read(source))
    return AnswerKey(
        job_id=document["job_id"],
        provenance=document["provenance"],
        steps=_steps("answer_key", document["steps"]),
    )


def check_against_job(submission: Submission, job: Job) -> None:
    """The rules that need the job: same job, inside the clip, under the limits. Lateness is separate."""
    if submission.job_id != job.job_id:
        raise ProtocolError(f"submission: job_id: {submission.job_id!r} is not this job ({job.job_id!r})")
    if len(submission.steps) > job.max_steps:
        raise ProtocolError(
            f"submission: steps: {len(submission.steps)} steps, the job allows {job.max_steps}"
        )
    for index, step in enumerate(submission.steps):
        if step.end_s > job.duration_s:
            raise ProtocolError(
                f"submission: steps/{index}/end_s: past the end of the clip ({job.duration_s}s)"
            )
        for field in ("action", "object"):
            if len(getattr(step.caption, field)) > job.max_caption_chars:
                raise ProtocolError(
                    f"submission: steps/{index}/caption/{field}: over {job.max_caption_chars} characters"
                )


def is_late(submission: Submission, job: Job) -> bool:
    """Whether the submission missed the deadline. Late work scores zero; it is not rejected here."""
    return submission.submitted_at > job.deadline


def to_document(value: Job | Submission | AnswerKey) -> dict[str, Any]:
    """The JSON form of a value, as the wire carries it."""
    if isinstance(value, Job):
        if value.raw is None:
            raise ValueError("a job built in code has no document; load one from JSON")
        return value.raw
    steps = [
        {
            "start_s": step.start_s,
            "end_s": step.end_s,
            "caption": {
                "action": step.caption.action,
                "object": step.caption.object,
                "hand": step.caption.hand,
            },
        }
        for step in value.steps
    ]
    if isinstance(value, Submission):
        document: dict[str, Any] = {
            "job_id": value.job_id,
            "miner_hotkey": value.miner_hotkey,
            "submitted_at": value.submitted_at.isoformat().replace("+00:00", "Z"),
            "steps": steps,
        }
        if value.method:
            document["method"] = value.method
        return document
    return {"job_id": value.job_id, "provenance": value.provenance, "steps": steps}
