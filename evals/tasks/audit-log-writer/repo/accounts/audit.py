"""The audit trail: one line per security-relevant event."""

import time


def write_audit_line(path: str, actor: str, action: str) -> None:
    """Old helper from before AuditTrail; kept for the import scripts."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{int(time.time())} {actor} {action}\n")


class AuditTrail:
    def __init__(self, sink, clock=time.time) -> None:
        self._sink = sink
        self._clock = clock

    def record(self, actor: str, action: str, **details: object) -> None:
        extra = " ".join(f"{key}={value}" for key, value in sorted(details.items()))
        self._sink.emit(f"{int(self._clock())} {actor} {action} {extra}".rstrip())
