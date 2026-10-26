"""
A human workflow. The first time a job is seen, a template is written to the work folder
(THOR_MINER_WORK_DIR, default ./work) with the clip's address, the instructions and the
step format; the pipeline then returns None, so the miner moves on. Once someone has filled
the template in, the next pass reads the steps from it and submits them. Slow work fits
because the queue is pulled, not pushed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from thor.models import Job, Step, steps_from_documents

TEMPLATE_STEP = {
    "start_s": 0.0,
    "end_s": 0.0,
    "caption": {"action": "", "object": "", "hand": "left|right|both"},
}


def work_dir() -> Path:
    return Path(os.environ.get("THOR_MINER_WORK_DIR", "work"))


def template_path(job: Job) -> Path:
    return work_dir() / f"{job.job_id}.json"


def label_video(job: Job) -> Sequence[Step] | None:
    path = template_path(job)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "video_url": job.video_url,
                    "duration_s": job.duration_s,
                    "task": job.title,
                    "instructions": job.instructions,
                    "deadline": job.deadline.isoformat(),
                    "how_to": (
                        "Replace the steps below with what happens in the clip, in order, "
                        "then run the miner again."
                    ),
                    "steps": [TEMPLATE_STEP],
                },
                indent=2,
            )
        )
        return None
    document = json.loads(path.read_text())
    steps = document.get("steps", [])
    if not steps or steps == [TEMPLATE_STEP]:
        return None
    return steps_from_documents("template", steps)
