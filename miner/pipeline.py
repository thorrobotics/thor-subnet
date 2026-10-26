"""
The one thing a miner replaces: how a job's video becomes steps. A pipeline is a function
from a job to the steps, or to None when it has nothing to hand in yet (a person is still
working on it, say). Everything else in the miner, fetching, checking and submitting, stays
the same whatever the method, because the network pays for the output, not the method.

    def label_video(job: Job) -> Sequence[Step] | None: ...

Pick one with `thor-miner --pipeline example`, `--pipeline manual`, or
`--pipeline some.module:function` for your own.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from importlib import import_module

from thor.models import Job, Step

Pipeline = Callable[[Job], Sequence[Step] | None]

BUILT_IN = {
    "example": "miner.pipelines.example:label_video",
    "manual": "miner.pipelines.manual:label_video",
}


def load_pipeline(name: str) -> Pipeline:
    """A built-in pipeline by name, or `module:function` for your own."""
    target = BUILT_IN.get(name, name)
    if ":" not in target:
        raise ValueError(f"unknown pipeline {name!r}; use one of {sorted(BUILT_IN)} or module:function")
    module_name, function_name = target.split(":", 1)
    return getattr(import_module(module_name), function_name)
