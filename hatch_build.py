"""Puts the built web UI (web/out) into the wheel as zwans/web, so `zwans serve` has it when
Zwans is installed with `uv tool install .` or `pip install .`. Build the UI first; without
it the wheel is still built, and the server shows a note instead of the UI.

Editable installs skip this: they serve web/out from the checkout directly."""

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        built = Path(self.root) / "web" / "out"
        if self.target_name == "wheel" and version == "standard" and built.is_dir():
            build_data["force_include"][str(built)] = "zwans/web"
