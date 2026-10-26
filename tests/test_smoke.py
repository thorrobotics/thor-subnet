import miner.run
import mock_server.app
import thor
import validator.run


def test_packages_import() -> None:
    assert thor.__doc__
    assert callable(miner.run.main)
    assert callable(validator.run.main)
    assert callable(mock_server.app.main)
