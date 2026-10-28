from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from libsys.config import ConfigError, load_branches, parse_offset


def test_branches_file(branches) -> None:
    assert [branch.code for branch in branches] == ["HAR", "HIL"]
    hillside = branches.get("HIL")
    assert hillside.name == "Hillside"
    assert hillside.loan_days == 14
    assert hillside.utc_offset == timedelta(hours=13)
    assert hillside.fine_cap == Decimal("5.00")
    assert branches.default.code == "HAR"


def test_resolve_by_name_in_any_case(branches) -> None:
    assert branches.resolve("Harbour").code == "HAR"
    assert branches.resolve("hillside").code == "HIL"
    assert branches.resolve("  HILLSIDE ").code == "HIL"


def test_an_empty_branch_is_the_default(branches) -> None:
    assert branches.resolve("") is branches.default
    assert branches.resolve("   ") is branches.default


def test_offsets() -> None:
    assert parse_offset("+05:30") == timedelta(hours=5, minutes=30)
    assert parse_offset("-03:00") == timedelta(hours=-3)
    with pytest.raises(ConfigError):
        parse_offset("13")


def test_bad_branch_files(tmp_path: Path) -> None:
    path = tmp_path / "branches.toml"
    path.write_text(
        'default = "X"\n[[branch]]\ncode = "A"\nname = "A"\nloan_days = 7\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="default branch"):
        load_branches(path)
    path.write_text('default = "A"\n[[branch]]\ncode = "A"\nname = "A"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="loan_days"):
        load_branches(path)
