from pathlib import Path

import pytest
import strata

CONFIG = Path(__file__).resolve().parents[1] / "config"


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_sections_and_scalars(tmp_path: Path) -> None:
    path = write(tmp_path, "a.st", "name = demo\n[server]\nport = 8080\ndebug = true\n")

    assert strata.load(path) == {"name": "demo", "server": {"port": 8080, "debug": True}}


def test_lists(tmp_path: Path) -> None:
    path = write(tmp_path, "a.st", "tags = [a, b, c]\n")

    assert strata.load(path) == {"tags": ["a", "b", "c"]}


def test_simple_reference(tmp_path: Path) -> None:
    path = write(tmp_path, "a.st", "[server]\nhost = example.org\nurl = https://${server.host}/\n")

    assert strata.load(path)["server"]["url"] == "https://example.org/"


def test_unknown_line_is_an_error(tmp_path: Path) -> None:
    path = write(tmp_path, "a.st", "[server]\nthis is not valid\n")

    with pytest.raises(strata.ConfigError):
        strata.load(path)


def test_the_service_configuration_loads() -> None:
    config = strata.load(CONFIG / "service.st", env={"DEPLOY_ENV": "prod"})

    assert config["server"]["url"] == "http://0.0.0.0:8080/"
    assert config["storage"]["bucket"] == "ingest-prod"
