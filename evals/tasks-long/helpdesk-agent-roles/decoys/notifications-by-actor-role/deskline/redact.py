"""Hiding customers' contact details from people who may not see them."""

from __future__ import annotations

from typing import Any

REDACTED = "[redacted]"

# Fields of a customer that are contact details.
CONTACT_FIELDS = ("email", "phone", "address")
# Keys that carry contact details in audit entries and other plain-dict output.
CONTACT_KEYS = CONTACT_FIELDS + ("from_address", "requester_email", "requester_phone")


def value(text: Any, hide: bool) -> Any:
    """``[redacted]`` in place of a non-empty value when hiding."""
    if hide and text:
        return REDACTED
    return text


def fields(data: dict[str, Any], hide: bool, keys: tuple[str, ...] = CONTACT_KEYS) -> dict[str, Any]:
    if not hide:
        return data
    return {k: (value(v, True) if k in keys else v) for k, v in data.items()}


def details(data: Any, hide: bool) -> Any:
    """Redact contact keys anywhere in a nested structure (audit details, ``changes``)."""
    if not hide:
        return data
    if isinstance(data, dict):
        out = {}
        for key, item in data.items():
            if key in CONTACT_KEYS:
                if isinstance(item, list):
                    out[key] = [value(v, True) for v in item]
                elif isinstance(item, (str, int, float)):
                    out[key] = value(item, True)
                else:
                    out[key] = details(item, hide)
            else:
                out[key] = details(item, hide)
        return out
    if isinstance(data, list):
        return [details(item, hide) for item in data]
    return data
