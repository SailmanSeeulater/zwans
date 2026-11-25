"""logq: search log lines with a small, predictable pattern language."""

from logq.meter import Meter, StepLimitExceeded
from logq.pattern import Pattern, compile
from logq.syntax import PatternError

__all__ = ["Meter", "Pattern", "PatternError", "StepLimitExceeded", "compile"]
