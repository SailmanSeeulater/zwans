class Outbox:
    """Messages are queued to a file that a separate process sends."""

    def __init__(self, path: str) -> None:
        self.path = path

    def send(self, user_id: int, text: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(f"{user_id}\t{text}\n")
