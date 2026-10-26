"""Shared by the tests: where the examples are, a hotkey, and a mock queue on a free port."""

import json
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from mock_server.app import Queue, serve
from thor.examples import examples_dir

EXAMPLES: Path = examples_dir()
HOTKEY = "5FQmDdKuJgkkBhY2Bd4gdBcPy79DkBaFCXtawBp1e48zuvDW"


def example(name: str) -> dict:
    """One of the example documents, parsed."""
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def running(deadline: timedelta):
    """A queue serving the examples on a free port, for the duration of a test."""
    queue = Queue.from_examples(EXAMPLES, deadline)
    httpd = serve(queue, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


@pytest.fixture
def server():
    """A queue with an hour to answer each job."""
    yield from running(timedelta(hours=1))


@pytest.fixture
def late():
    """A queue whose deadline has passed the moment a job is served."""
    yield from running(timedelta(0))
