BOOLEANS = {"true": True, "false": False, "yes": True, "no": False}


def load(raw: dict[str, str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in raw.items():
        out[key] = BOOLEANS.get(value.lower(), value)
    return out
