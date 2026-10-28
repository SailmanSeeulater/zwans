from dataclasses import dataclass
from datetime import UTC, datetime

MAX_BODY = 500


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Post:
    id: int
    author: str
    created_at: datetime  # aware, UTC, whole seconds
    body: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "author": self.author,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "body": self.body,
        }


def check_username(name: str) -> str:
    name = name.strip().lower()
    if not name or not name.replace("_", "").isalnum() or len(name) > 30:
        raise ValidationError(f"not a valid username: {name!r}")
    return name


def check_body(body: str) -> str:
    body = body.strip()
    if not body:
        raise ValidationError("a post can't be empty")
    if len(body) > MAX_BODY:
        raise ValidationError(f"a post can be at most {MAX_BODY} characters")
    return body


def utc_seconds(moment: datetime) -> datetime:
    """Timestamps are kept to the second, in UTC."""
    if moment.tzinfo is None:
        raise ValidationError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).replace(microsecond=0)
