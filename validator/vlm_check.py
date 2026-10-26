"""
Fact checking a submission's captions with a vision language model, for jobs with no answer
key. The backend is the part that changes: V1 ships the interface and a stub that accepts
everything (and so, as docs/validators.md says, calibrates at 0.5). A real backend would
download the clip, show the model the span between a step's start and end, and ask whether
the caption describes it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from thor.models import Job, Step

PASS_SHARE = 0.8
"""A submission passes a fact check when at least this share of its captions is accepted."""


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    confidence: float
    note: str = ""


class Backend(Protocol):
    name: str

    def judge(self, job: Job | None, step: Step) -> Verdict:
        """Whether the caption describes what happens between the step's start and end."""
        ...


class StubBackend:
    """Accepts every caption. Useful only to run the loop; it cannot tell good work from bad."""

    name = "stub"

    def judge(self, job: Job | None, step: Step) -> Verdict:
        return Verdict(accepted=True, confidence=0.5, note="stub backend accepts everything")


@dataclass(frozen=True)
class FactCheck:
    verdicts: tuple[Verdict, ...]

    @property
    def accepted_share(self) -> float:
        return sum(v.accepted for v in self.verdicts) / len(self.verdicts) if self.verdicts else 0.0

    @property
    def passed(self) -> bool:
        return self.accepted_share >= PASS_SHARE


def fact_check(backend: Backend, job: Job | None, steps: Sequence[Step]) -> FactCheck:
    return FactCheck(tuple(backend.judge(job, step) for step in steps))
