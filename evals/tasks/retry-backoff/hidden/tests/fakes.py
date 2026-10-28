from typing import Any


class FakeTransport:
    """Plays back a script of answers. An answer that is an exception is raised instead."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, path: str, params: dict[str, str]) -> Any:
        self.calls.append((path, params))
        if not self.answers:
            raise AssertionError("the transport was called more often than expected")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer
