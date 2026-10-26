import json
from datetime import timedelta
from pathlib import Path

import pytest

from miner.pipeline import load_pipeline
from miner.pipelines import manual
from miner.run import run_once
from thor.client import Client, ClientError
from thor.models import Caption, Step

from .test_mock_server import HOTKEY, running

server = pytest.fixture(lambda: (yield from running(timedelta(hours=1))))


def test_example_pipeline_runs_the_loop(server: str) -> None:
    lines: list[str] = []
    receipt = run_once(Client(server, HOTKEY), load_pipeline("example"), "automated", log=lines.append)
    assert receipt and receipt["score"]["total"] == pytest.approx(0.95, abs=1e-3)
    assert any("score 0.95" in line for line in lines)
    assert run_once(Client(server, HOTKEY), load_pipeline("example"), log=lines.append) is None
    assert lines[-1].endswith("nothing for this hotkey")


def test_manual_pipeline_waits_for_a_person(server: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOR_MINER_WORK_DIR", str(tmp_path))
    client = Client(server, HOTKEY)
    lines: list[str] = []
    assert run_once(client, load_pipeline("manual"), log=lines.append) is None
    template = tmp_path / "job_000001_fold_towel.json"
    assert template.exists() and "nothing to hand in yet" in lines[-1]

    document = json.loads(template.read_text())
    document["steps"] = json.loads(
        (Path(__file__).resolve().parent.parent / "examples" / "submission.json").read_text()
    )["steps"]
    template.write_text(json.dumps(document))
    receipt = run_once(client, load_pipeline("manual"), "human", log=lines.append)
    assert receipt and receipt["score"]["total"] == pytest.approx(0.95, abs=1e-3)


def test_bad_work_is_never_sent(server: str) -> None:
    def overlapping(job):
        return (
            Step(0.0, 5.0, Caption("pick up", "towel", "both")),
            Step(4.0, 9.0, Caption("fold", "towel", "both")),
        )

    lines: list[str] = []
    assert run_once(Client(server, HOTKEY), overlapping, log=lines.append) is None
    assert "fails the protocol" in lines[-1] and "steps/1/start_s" in lines[-1]
    assert Client(server, HOTKEY).latest("job_000001_fold_towel") is None


def test_client_reports_what_the_queue_said(server: str) -> None:
    with pytest.raises(ClientError, match="HTTP 401"):
        Client(server, "").next_job()
    with pytest.raises(ClientError, match="cannot reach"):
        Client("http://127.0.0.1:9", HOTKEY).next_job()


def test_manual_template_is_left_alone_until_filled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOR_MINER_WORK_DIR", str(tmp_path))
    from thor.models import load_job

    job = load_job(Path(__file__).resolve().parent.parent / "examples" / "job.json")
    assert manual.label_video(job) is None
    assert manual.label_video(job) is None, "an unfilled template is not a submission"
