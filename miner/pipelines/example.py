"""
A stand-in for an automated pipeline. It does not look at the video: for the example job it
returns the example submission's steps (from the checkout's examples folder, see
thor.examples), and for any other job a single step spanning the clip, which is what a real
model would replace. It exists so the loop can be run end to end.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from thor.examples import examples_dir
from thor.models import Caption, Job, Step, load_submission


def label_video(job: Job) -> Sequence[Step]:
    example = examples_dir() / "submission.json"
    if not example.exists():
        raise FileNotFoundError(f"{example} not found; run from a checkout or set THOR_EXAMPLES_DIR")
    if json.loads(example.read_text()).get("job_id") == job.job_id:
        return load_submission(example).steps
    return (
        Step(
            start_s=0.0,
            end_s=job.duration_s,
            caption=Caption(action="perform", object=job.title.lower(), hand="both"),
        ),
    )
