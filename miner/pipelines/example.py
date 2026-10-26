"""
A stand-in for an automated pipeline. It does not look at the video: for the example job it
returns the example submission's steps, and for any other job a single step spanning the
clip, which is what a real model would replace. It exists so the loop can be run end to end.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from thor.models import Caption, Job, Step, load_submission

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "submission.json"


def label_video(job: Job) -> Sequence[Step]:
    if EXAMPLE.exists() and json.loads(EXAMPLE.read_text()).get("job_id") == job.job_id:
        return load_submission(EXAMPLE).steps
    return (
        Step(
            start_s=0.0,
            end_s=job.duration_s,
            caption=Caption(action="perform", object=job.title.lower(), hand="both"),
        ),
    )
