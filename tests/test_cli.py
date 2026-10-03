from typer.testing import CliRunner

from zwans import __version__
from zwans.cli.app import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"zwans {__version__}"
