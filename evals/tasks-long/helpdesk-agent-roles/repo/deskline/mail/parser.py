"""Reading inbound mail.

Turns a raw RFC 5322 message into the parts deskline cares about: who sent it, the
subject, which ticket it answers (from a ``[T-12]`` tag in the subject), and the new text
with quoted history and signatures cut off.
"""

from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from email.utils import getaddresses, parseaddr

from ..errors import MailError

_TICKET_TAG = re.compile(r"\[(T-\d+)\]")
_REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|sv)\s*:\s*)+", re.I)
_QUOTE_HEADER = re.compile(r"^On .{4,200}wrote:\s*$")
_ORIGINAL = re.compile(r"^-{2,}\s*(Original Message|Forwarded message)\s*-{2,}", re.I)
_AUTO_SUBMITTED = ("auto-replied", "auto-generated", "auto-notified")


@dataclass
class InboundMail:
    sender_name: str
    sender_address: str
    subject: str
    body: str
    ticket_ref: str | None = None
    message_id: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    automatic: bool = False

    @property
    def clean_subject(self) -> str:
        subject = _TICKET_TAG.sub("", self.subject)
        subject = _REPLY_PREFIX.sub("", subject)
        return " ".join(subject.split()) or "(no subject)"


def _text_part(message: email.message.EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
    return text


def strip_quoted(text: str) -> str:
    """Keep only the new part of a reply."""
    kept = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith(">") or _QUOTE_HEADER.match(line) or _ORIGINAL.match(line):
            break
        if line.rstrip() == "--" or line == "-- ":
            break
        kept.append(line.rstrip())
    while kept and not kept[-1]:
        kept.pop()
    while kept and not kept[0]:
        kept.pop(0)
    return "\n".join(kept)


def parse(raw: str) -> InboundMail:
    message = email.message_from_string(raw, policy=email.policy.default)
    name, address = parseaddr(str(message.get("From", "")))
    if not address or "@" not in address:
        raise MailError("message has no usable From address")
    subject = str(message.get("Subject", "")).strip()
    body = strip_quoted(_text_part(message))
    match = _TICKET_TAG.search(subject)
    auto = str(message.get("Auto-Submitted", "")).lower() in _AUTO_SUBMITTED or bool(
        message.get("X-Autoreply")
    )
    return InboundMail(
        sender_name=name.strip() or address.split("@")[0],
        sender_address=address.strip().lower(),
        subject=subject,
        body=body,
        ticket_ref=match.group(1) if match else None,
        message_id=str(message.get("Message-ID", "")).strip(),
        to=[a for _, a in getaddresses([str(v) for v in message.get_all("To", [])])],
        cc=[a for _, a in getaddresses([str(v) for v in message.get_all("Cc", [])])],
        automatic=auto,
    )
