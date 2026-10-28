"""Settings come from DEFAULTS, then the chosen profile, then explicit overrides."""

DEFAULTS = {
    "profile": "production",
    "audit_sink": "plain",
    "audit_path": "audit.log",
    "audit_max_bytes": 64_000,
    "outbox_path": "outbox.txt",
}

PROFILES = {
    "production": {"audit_sink": "rotating"},
    "development": {"audit_sink": "stderr"},
    "test": {"audit_sink": "memory"},
}


def load_settings(**overrides: object) -> dict:
    profile = overrides.get("profile", DEFAULTS["profile"])
    return {**DEFAULTS, **PROFILES[profile], **overrides}
