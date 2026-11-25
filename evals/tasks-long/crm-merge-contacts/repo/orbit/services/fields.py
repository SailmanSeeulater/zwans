"""Custom fields: extra, typed values on contacts that each team defines for itself.

    text     any text
    number   an integer or a decimal number
    date     YYYY-MM-DD
    choice   one of the field's choices
    multi    any number of the field's choices, as a list

Setting a field to None, "" or [] clears it.
"""

import re
from datetime import date

from orbit.errors import Conflict, InvalidValue, NotFound
from orbit.models import FIELD_TYPES, Contact, FieldDef
from orbit.services.base import Service
from orbit.services.contacts import ContactService
from orbit.text import split_list, unique

NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def is_empty(value) -> bool:
    return value is None or value == "" or value == []


class FieldService(Service):
    def __init__(self, *args, contacts: ContactService) -> None:
        super().__init__(*args)
        self.contacts = contacts

    def define(self, name: str, type: str = "text", label: str = "", choices=()) -> FieldDef:
        if not NAME.match(name):
            raise InvalidValue(f"{name!r} is not a field name (a-z, 0-9 and _).")
        if type not in FIELD_TYPES:
            raise InvalidValue(f"Field types are {', '.join(FIELD_TYPES)}.")
        if self.store.has("fields", name):
            raise Conflict(f"There is already a field called {name!r}.")
        choices = unique(choice.strip() for choice in choices if choice.strip())
        if type in ("choice", "multi") and not choices:
            raise InvalidValue(f"A {type} field needs choices.")
        definition = FieldDef(id=name, type=type, label=label or name, choices=choices)
        self.store.put("fields", definition.to_row())
        return definition

    def definition(self, name: str) -> FieldDef:
        row = self.store.get("fields", name)
        if row is None:
            raise NotFound("field", name)
        return FieldDef.from_row(row)

    def definitions(self) -> list[FieldDef]:
        return [FieldDef.from_row(row) for row in self.store.rows("fields")]

    def set(self, contact_id: str, name: str, value) -> Contact:
        row = self.store.get("contacts", contact_id)
        if row is None:
            raise NotFound("contact", contact_id)
        contact = Contact.from_row(row)
        value = self.coerce(self.definition(name), value)
        if value is None:
            if name not in contact.fields:
                return contact
            del contact.fields[name]
        else:
            if contact.fields.get(name) == value:
                return contact
            contact.fields[name] = value
        self.contacts.save(contact, ["fields"])
        return contact

    def coerce(self, definition: FieldDef, value):
        if is_empty(value):
            return None
        kind = definition.type
        if kind == "text":
            return str(value).strip() or None
        if kind == "number":
            return _number(definition.name, value)
        if kind == "date":
            try:
                return date.fromisoformat(str(value).strip()).isoformat()
            except ValueError:
                raise InvalidValue(f"{definition.name}: {value!r} is not a date.") from None
        if kind == "choice":
            value = str(value).strip()
            if value not in definition.choices:
                raise InvalidValue(f"{definition.name}: {value!r} is not one of the choices.")
            return value
        values = split_list(value) if isinstance(value, str) else [str(v).strip() for v in value]
        for item in values:
            if item not in definition.choices:
                raise InvalidValue(f"{definition.name}: {item!r} is not one of the choices.")
        return unique(values) or None

    def render(self, definition: FieldDef, value) -> str:
        if is_empty(value):
            return ""
        if definition.type == "multi":
            return "; ".join(value)
        return str(value)


def _number(name: str, value):
    if isinstance(value, bool):
        raise InvalidValue(f"{name}: {value!r} is not a number.")
    if isinstance(value, (int, float)):
        number = value
    else:
        try:
            number = float(str(value).strip())
        except ValueError:
            raise InvalidValue(f"{name}: {value!r} is not a number.") from None
    return int(number) if float(number).is_integer() else float(number)
