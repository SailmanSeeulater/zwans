from pathlib import Path

import pytest

from zwans.config import (
    Config,
    ConfigError,
    load_config,
    load_credential,
    load_settings,
    read_dotenv,
)


def test_defaults_when_there_is_no_file_or_env(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.toml", env={}) == Config()


def test_env_overrides_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "from-file"\nauth = "subscription"\n', encoding="utf-8")

    config = load_config(path, env={"ZWANS_MODEL": "from-env"})

    assert config.model == "from-env"
    assert config.auth == "subscription"


def test_zwans_config_names_another_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "project.toml"
    path.write_text('model = "from-zwans-config"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("ZWANS_CONFIG", str(path))
    monkeypatch.setenv("ZWANS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ZWANS_MODEL", raising=False)

    config, _ = load_settings()

    assert config.model == "from-zwans-config"


def test_the_home_dotenv_works_everywhere_and_the_local_one_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / ".env").write_text("ANTHROPIC_API_KEY=sk-home\nZWANS_MODEL=from-home\n")
    (project / ".env").write_text("ANTHROPIC_API_KEY=sk-project\n")
    (tmp_path / "empty.toml").write_text("")  # not the real config file
    monkeypatch.setenv("ZWANS_HOME", str(home))
    monkeypatch.setenv("ZWANS_CONFIG", str(tmp_path / "empty.toml"))
    for name in ("ANTHROPIC_API_KEY", "ZWANS_MODEL"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.chdir(tmp_path)
    config, env = load_settings()
    assert env["ANTHROPIC_API_KEY"] == "sk-home" and config.model == "from-home"

    monkeypatch.chdir(project)
    _, env = load_settings()
    assert env["ANTHROPIC_API_KEY"] == "sk-project"


def test_a_blank_line_in_the_folders_dotenv_doesnt_hide_the_home_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (home / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=oauth-home\n")
    # As copied from .env.example and never filled in.
    (project / ".env").write_text("ANTHROPIC_API_KEY=sk-project\nCLAUDE_CODE_OAUTH_TOKEN=\n")
    (tmp_path / "plan.toml").write_text('auth = "subscription"\n')
    monkeypatch.setenv("ZWANS_HOME", str(home))
    monkeypatch.setenv("ZWANS_CONFIG", str(tmp_path / "plan.toml"))
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ZWANS_AUTH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(project)

    config, env = load_settings()

    assert load_credential(config, env).token == "oauth-home"


def test_a_bad_setting_names_where_it_came_from(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('max_stpes = 5\neffort = "extreme"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_config(path, env={"ZWANS_AUTH": "oauth"})

    message = str(caught.value)
    assert "ZWANS_AUTH: Input should be 'api_key' or 'subscription'" in message
    assert f"max_stpes in {path}: isn't a setting" in message
    assert f"effort in {path}: Input should be" in message


def test_a_config_file_that_isnt_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "x\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="isn't valid TOML"):
        load_config(path, env={})


def test_zwans_config_naming_a_missing_file_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZWANS_CONFIG", str(tmp_path / "missing.toml"))

    with pytest.raises(ConfigError, match="doesn't exist"):
        load_settings()


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
    }


def test_a_missing_dotenv_is_empty(tmp_path: Path) -> None:
    assert read_dotenv(tmp_path / ".env") == {}


def test_missing_credential_points_to_the_one_that_is_set() -> None:
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "oauth-test"}

    with pytest.raises(ConfigError, match="set ZWANS_AUTH=subscription"):
        load_credential(Config(auth="api_key"), env)
