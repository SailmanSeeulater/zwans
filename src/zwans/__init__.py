"""Zwans: a coding agent built from scratch."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("zwans")
except PackageNotFoundError:  # run from a checkout without installing, as in runtime/dev.sh
    __version__ = "0.1.0+source"
