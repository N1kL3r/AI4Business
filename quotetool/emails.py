"""Load inquiry emails: plain text (header lines, blank line, body) or .eml files."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from pathlib import Path

HEADER_KEYS = ("from", "to", "cc", "date", "subject", "attachments")


@dataclass
class Email:
    case_id: str
    text: str                                   # the full email, exactly as saved
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""

    @property
    def attachments(self) -> list[str]:
        raw = self.headers.get("attachments", "")
        # Several attachments are separated by ";" (or "," when no name contains a comma).
        sep = ";" if ";" in raw else ","
        return [a.strip() for a in raw.split(sep) if a.strip()]


def parse_email_text(text: str, case_id: str) -> Email:
    """Plain-text email: header lines, a blank line, then the body."""
    text = text.replace("\r\n", "\n")
    head, _, body = text.partition("\n\n")
    headers = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in HEADER_KEYS:
            headers[key.strip().lower()] = value.strip()
    if not headers:  # pasted body only, no header block
        body = text
    return Email(case_id=case_id, text=text, headers=headers, body=body.strip())


def parse_eml(data: bytes, case_id: str) -> Email:
    """A .eml file as saved from Outlook, Thunderbird or Apple Mail: keep headers, text body and attachment names."""
    msg = BytesParser(policy=policy.default).parsebytes(data)
    part = msg.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part is not None else ""
    if part is not None and part.get_content_type() == "text/html":
        body = re.sub(r"<[^>]+>", " ", body)
    names = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
    lines = [f"{k.capitalize()}: {msg[k]}" for k in ("from", "to", "cc", "date", "subject") if msg[k]]
    if names:
        lines.append("Attachments: " + "; ".join(names))
    return parse_email_text("\n".join(lines) + "\n\n" + body.strip(), case_id)


def load_email(path: str | Path) -> Email:
    path = Path(path)
    if path.suffix.lower() == ".eml":
        return parse_eml(path.read_bytes(), path.stem)
    return parse_email_text(path.read_text(encoding="utf-8"), path.stem)


def load_inbox(folder: str | Path) -> dict[str, Email]:
    return {p.stem: load_email(p) for p in sorted(Path(folder).glob("*.txt"))}
