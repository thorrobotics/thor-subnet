"""The whole loop on one machine: a miner labels the example job, then a validator scores it."""

from miner.pipeline import load_pipeline
from miner.run import run_once as mine_once
from thor.client import Client
from validator.run import run_once as validate_once

from .conftest import HOTKEY


def test_miner_then_validator(server: str) -> None:
    assert mine_once(Client(server, HOTKEY), load_pipeline("example"), log=lambda line: None)
    lines: list[str] = []
    weights = validate_once(Client(server, "validator"), log=lines.append)
    assert weights == {HOTKEY: 1.0}
    assert any("scored 0.9500" in line for line in lines)
    assert any("balanced accuracy 1.00" in line for line in lines)
    assert any("no weights are set" in line for line in lines)
