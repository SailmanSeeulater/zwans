from dataclasses import dataclass

from ..aggregate import OrderState
from ..commands import Command, Context, handler, require_text
from ..errors import ValidationError
from ..events import Event, NoteAdded

MAX_NOTE = 500


@dataclass(frozen=True)
class AddNote(Command):
    text: str

    def validate(self) -> None:
        require_text(self.text, "note")
        if len(self.text) > MAX_NOTE:
            raise ValidationError(f"notes are at most {MAX_NOTE} characters")


@handler(AddNote, name="note", permission="orders.note", summary="Add an internal note to an order")
def note(state: OrderState, cmd: AddNote, ctx: Context) -> list[Event]:
    return [NoteAdded(cmd.order_id, ctx.at, ctx.actor.name, cmd.text.strip())]
