from pathlib import Path

import pytest

from zwans.config import Config, ConfigError, load_config, load_credential, read_dotenv


def test_defaults_when_there_is_no_file_or_env(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.toml", env={}) == Config()


def test_env_overrides_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "from-file"\nauth = "subscription"\n', encoding="utf-8")

    config = load_config(path, env={"ZWANS_MODEL": "from-env"})

    assert config.model == "from-env"
    assert config.auth == "subscription"


def test_credential_follows_the_auth_mode() -> None:
    env = {"ANTHROPIC_API_KEY": "sk-test", "CLAUDE_CODE_OAUTH_TOKEN": "oauth-test"}

    assert load_credential(Config(auth="api_key"), env).token == "sk-test"
    assert load_credential(Config(auth="subscription"), env).token == "oauth-test"


def test_missing_credential_says_how_to_fix_it() -> None:
    with pytest.raises(ConfigError, match="claude setup-token"):
        load_credential(Config(auth="subscription"), env={})


def test_dotenv_reads_values_and_skips_comments(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        '# a comment\nZWANS_AUTH=subscription\nANTHROPIC_API_KEY="sk-quoted"\nEMPTY=\n',
        encoding="utf-8",
    )

    assert read_dotenv(path) == {
        "ZWANS_AUTH": "subscription",
        "ANTHROPIC_API_KEY": "sk-quoted",
        "EMPTY": "",
    }


def test_a_missing_dotenv_is_empty(tmp_path: Path) -> None:
    assert read_dotenv(tmp_path / ".env") == {}
