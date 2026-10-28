"""Everything the policy engine needs, loaded once."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ledgerdesk.config import load_config
from ledgerdesk.config.loader import PROJECT_ROOT
from ledgerdesk.directory import Directory, load_directory
from ledgerdesk.invoices import InvoiceBook, load_invoices
from ledgerdesk.money import Rates, load_rates
from ledgerdesk.plugins import Plugin, load_plugins
from ledgerdesk.policy.delegation import Delegation, load_delegations
from ledgerdesk.policy.roles import Binding, RoleBook, load_bindings


@dataclass
class Context:
    config: dict[str, Any]
    root: Path
    directory: Directory
    roles: RoleBook
    bindings: list[Binding]
    delegations: list[Delegation]
    invoices: InvoiceBook
    rates: Rates
    plugins: list[Plugin]

    @property
    def env(self) -> str:
        return self.config["env"]

    def path(self, name: str) -> Path:
        """The data file configured as `data.<name>`, relative to the project root."""
        return self.root / self.config["data"][name]

    def feature(self, name: str) -> bool:
        return bool(self.config.get("features", {}).get(name, False))


def build_context(env: str | None = None, root: Path = PROJECT_ROOT) -> Context:
    config = load_config(env, root / "config")
    data = config["data"]
    directory = load_directory(root / data["directory"])
    roles = RoleBook(config.get("roles", {}))
    return Context(
        config=config,
        root=root,
        directory=directory,
        roles=roles,
        bindings=load_bindings(config, roles, directory),
        delegations=load_delegations(root / data["delegations"]),
        invoices=load_invoices(root / data["invoices"]),
        rates=load_rates(root / data["rates"]),
        plugins=load_plugins(config.get("plugins", {}).get("enabled", [])),
    )
