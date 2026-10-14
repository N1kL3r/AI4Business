"""Load inquiry emails saved as plain text (header lines, blank line, body)."""
from __future__ import annotations

from dataclasses import dataclass, field
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


def load_email(path: str | Path) -> Email:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    head, _, body = text.partition("\n\n")
    headers = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in HEADER_KEYS:
            headers[key.strip().lower()] = value.strip()
    return Email(case_id=path.stem, text=text, headers=headers, body=body.strip())


def load_inbox(folder: str | Path) -> dict[str, Email]:
    return {p.stem: load_email(p) for p in sorted(Path(folder).glob("*.txt"))}
