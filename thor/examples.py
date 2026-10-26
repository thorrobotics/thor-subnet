"""
Where the example job, submission and answer key live. They are part of the source checkout,
not the installed package: THOR_EXAMPLES_DIR when set, else ./examples in the working
directory, else the checkout this file sits in. The mock server serves jobs from here and the
example pipeline reads its answer from here.
"""

from __future__ import annotations

import os
from pathlib import Path


def examples_dir() -> Path:
    configured = os.environ.get("THOR_EXAMPLES_DIR")
    if configured:
        return Path(configured)
    local = Path.cwd() / "examples"
    if any(local.glob("job*.json")):
        return local
    return Path(__file__).resolve().parent.parent / "examples"
