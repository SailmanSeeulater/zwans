"""Branches, read from branches.toml."""

import re
import tomllib
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from libsys.models import Branch


class ConfigError(Exception):
    pass


class UnknownBranch(LookupError):
    pass


_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def parse_offset(text: str) -> timedelta:
    match = _OFFSET.match(text.strip())
    if not match:
        raise ConfigError(f"utc_offset must look like +13:00, not {text!r}")
    sign, hours, minutes = match.groups()
    offset = timedelta(hours=int(hours), minutes=int(minutes))
    return -offset if sign == "-" else offset


def parse_money(text: object, what: str) -> Decimal:
    try:
        value = Decimal(str(text))
    except InvalidOperation as exc:
        raise ConfigError(f"{what} must be an amount like 0.25, not {text!r}") from exc
    if value < 0:
        raise ConfigError(f"{what} can't be negative")
    return value.quantize(Decimal("0.01"))


class BranchDirectory:
    def __init__(self, branches: list[Branch], default: str) -> None:
        if not branches:
            raise ConfigError("no branches configured")
        self.branches = {branch.code: branch for branch in branches}
        if default not in self.branches:
            raise ConfigError(f"the default branch {default!r} isn't one of the branches")
        self.default = self.branches[default]
        self._by_alias: dict[str, Branch] = {}
        for branch in branches:
            for alias in {_alias(branch.code), _alias(branch.name)}:
                if alias in self._by_alias:
                    raise ConfigError(f"two branches are called {alias!r}")
                self._by_alias[alias] = branch

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.branches.values())

    def get(self, code: str) -> Branch:
        try:
            return self.branches[code]
        except KeyError:
            raise UnknownBranch(code) from None

    def resolve(self, value: str) -> Branch:
        """The branch a desk export means: its code or its name, in any case, with or
        without surrounding spaces. An empty value means the default branch."""
        alias = _alias(value)
        if not alias:
            return self.default
        try:
            return self._by_alias[alias]
        except KeyError:
            raise UnknownBranch(value.strip()) from None


def _alias(value: str) -> str:
    return " ".join(value.split()).casefold()


def load_branches(path: Path) -> BranchDirectory:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} not found") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    branches = []
    for entry in data.get("branch", []):
        try:
            code = str(entry["code"]).strip().upper()
            branches.append(
                Branch(
                    code=code,
                    name=str(entry["name"]).strip(),
                    utc_offset=parse_offset(str(entry.get("utc_offset", "+00:00"))),
                    loan_days=int(entry["loan_days"]),
                    max_renewals=int(entry.get("max_renewals", 0)),
                    fine_per_day=parse_money(
                        entry.get("fine_per_day", "0"), f"{code} fine_per_day"
                    ),
                    fine_cap=parse_money(entry.get("fine_cap", "0"), f"{code} fine_cap"),
                )
            )
        except KeyError as exc:
            raise ConfigError(f"{path}: a branch is missing {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    return BranchDirectory(branches, str(data.get("default", "")).strip().upper())
