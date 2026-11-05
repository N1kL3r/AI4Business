"""Read an inquiry from almost any file a customer or colleague might hand us.

Emails (.eml, .msg, .mbox), Word and OpenDocument files, Excel sheets, PDFs, HTML, RTF, plain text, CSV,
exported chat logs (WhatsApp, Telegram, Teams, Slack), and ZIP archives of any of these. Several files can
be combined into one inquiry (for example the email plus the order sheet attached to it).

Reading never raises for a bad file: whatever cannot be read becomes a warning that the app shows, so the
person knows to paste that content by hand instead of silently getting a quote that missed it.
"""
from __future__ import annotations

import html
import io
import mailbox
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from .emails import Email, parse_email_text, parse_eml

MAX_CHARS = 300_000        # per file; longer texts are cut with a warning
MAX_ZIP_FILES = 40
MAX_ZIP_DEPTH = 2
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic"}
TEXT_TYPES = {".txt", ".text", ".md", ".log", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".ini", ".chat", ""}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# One line of an exported chat: WhatsApp "[12/05/2026, 10:14:02] Name: ...", "12/05/26, 10:14 - Name: ...",
# Telegram/Slack/Teams "Name, [12.05.2026 10:14]" or "Name  10:14 AM".
_CHAT_LINE = re.compile(
    r"^\s*(\[\s*\d{1,4}[./-]\d{1,2}[./-]\d{1,4}[,\s]+\d{1,2}:\d{2}(:\d{2})?\s*([AaPp][Mm])?\s*\]"
    r"|\d{1,4}[./-]\d{1,2}[./-]\d{1,4},?\s+\d{1,2}:\d{2}(:\d{2})?\s*([AaPp][Mm])?\s*[-–]\s"
    r"|[^\n:]{1,40},\s*\[\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\s+\d{1,2}:\d{2}[^\]]*\])")


@dataclass
class Ingested:
    email: Email
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)   # one line per file: what it was recognised as


# ---------- text clean-up ----------

def decode(data: bytes) -> str:
    """Bytes -> text without ever failing: BOM-marked UTF-8/16, UTF-8, then Windows-1252 (old Outlook, Excel)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if len(data) >= 4 and (data[1::2].count(0) > len(data) // 4 or data[0::2].count(0) > len(data) // 4):
        return data.decode("utf-16-le" if data[1::2].count(0) > data[0::2].count(0) else "utf-16-be", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def clean(text: str) -> str:
    """Normalise line endings and remove invisible characters that chat apps and Word sprinkle in."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]", "", text)
    text = text.replace("\u202f", " ").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def looks_like_chat(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hits = sum(bool(_CHAT_LINE.match(ln)) for ln in lines[:200])
    return hits >= 3 and hits >= 0.3 * min(len(lines), 200)


# ---------- format readers: bytes -> text ----------

class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(source: str) -> str:
    parser = _HTMLText()
    parser.feed(source)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(parser.parts))


def rtf_to_text(source: str) -> str:
    source = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), source)
    source = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), source)
    source = re.sub(r"\\(par|line|row)\b ?", "\n", source)
    source = re.sub(r"\\(tab|cell)\b ?", "\t", source)
    source = re.sub(r"\{\\\*[^{}]*\}|\{\\(fonttbl|colortbl|stylesheet|info)[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", source)
    source = re.sub(r"\\[a-zA-Z]+-?\d* ?|[{}]|\\", "", source)
    return source


def docx_to_text(data: bytes) -> str:
    """Paragraphs and tables (cells joined with tabs) from a .docx, in document order."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    def para(p):
        out = []
        for node in p.iter():
            if node.tag == _W + "t":
                out.append(node.text or "")
            elif node.tag == _W + "tab":
                out.append("\t")
            elif node.tag in (_W + "br", _W + "cr"):
                out.append("\n")
        return "".join(out)
    lines = []
    for el in root.find(_W + "body"):
        if el.tag == _W + "p":
            lines.append(para(el))
        elif el.tag == _W + "tbl":
            for row in el.iter(_W + "tr"):
                lines.append("\t".join(" ".join(para(p) for p in cell.iter(_W + "p")).strip()
                                       for cell in row.findall(_W + "tc")))
    return "\n".join(lines)


def odf_to_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("content.xml"))
    text = ET.tostring(root, encoding="unicode", method="xml")
    text = re.sub(r"</text:(p|h)>|</table:table-row>", "\n", text)
    text = re.sub(r"</table:table-cell>", "\t", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def xlsx_to_text(data: bytes) -> str:
    """Every sheet as tab-separated rows (values, not formulas)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_S + "t")))
        sheet_names = {}
        if "xl/workbook.xml" in names:
            sheet_names = {i: s.get("name") for i, s in enumerate(ET.fromstring(z.read("xl/workbook.xml")).iter(_S + "sheet"), 1)}
        out = []
        for n, path in enumerate(sorted((p for p in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", p)),
                                        key=lambda p: int(re.findall(r"\d+", p)[0])), 1):
            out.append(f"[Sheet: {sheet_names.get(n, n)}]")
            for row in ET.fromstring(z.read(path)).iter(_S + "row"):
                cells = []
                for c in row.findall(_S + "c"):
                    v = c.find(_S + "v")
                    if c.get("t") == "s" and v is not None and v.text is not None:
                        cells.append(shared[int(v.text)])
                    elif c.get("t") == "inlineStr":
                        cells.append("".join(t.text or "" for t in c.iter(_S + "t")))
                    else:
                        cells.append(v.text if v is not None and v.text else "")
                if any(cells):
                    out.append("\t".join(cells).rstrip("\t"))
    return "\n".join(out)


def pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF reading needs the 'pypdf' package (pip install pypdf)")
    return "\n\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)


def msg_to_email(data: bytes, case_id: str) -> Email:
    """Outlook .msg (needs the optional 'extract-msg' package)."""
    try:
        import extract_msg
    except ImportError:
        raise RuntimeError("Outlook .msg files need the 'extract-msg' package (pip install extract-msg), "
                           "or save the mail as .eml from Outlook")
    m = extract_msg.openMsg(io.BytesIO(data))
    try:
        names = [a.longFilename or a.shortFilename for a in m.attachments if (a.longFilename or a.shortFilename)]
        lines = [f"{k.capitalize()}: {v}" for k, v in
                 (("from", m.sender), ("to", m.to), ("cc", m.cc), ("date", m.date), ("subject", m.subject)) if v]
        if names:
            lines.append("Attachments: " + "; ".join(names))
        body = m.body or html_to_text(m.htmlBody.decode("utf-8", "replace") if m.htmlBody else "")
        return parse_email_text("\n".join(lines) + "\n\n" + clean(body), case_id)
    finally:
        m.close()


# ---------- one file ----------

def _read(name: str, data: bytes, depth: int, warnings: list[str], sources: list[str]) -> str:
    """Text of one file (zips are unpacked recursively). Problems go to `warnings`."""
    ext = Path(name).suffix.lower()
    try:
        if ext == ".eml":
            sources.append(f"{name}: email")
            return parse_eml(data, "x").text + _attachment_text(data, name, warnings)
        if ext == ".msg":
            sources.append(f"{name}: Outlook email")
            return msg_to_email(data, "x").text
        if ext == ".mbox":
            msgs = _mbox_messages(data)
            sources.append(f"{name}: mailbox with {len(msgs)} email(s)")
            return "\n\n----------\n\n".join(parse_eml(m, "x").text for m in msgs)
        if ext in (".docx", ".docm", ".dotx"):
            sources.append(f"{name}: Word document")
            return docx_to_text(data)
        if ext in (".odt", ".ods", ".odp"):
            sources.append(f"{name}: OpenDocument file")
            return odf_to_text(data)
        if ext in (".xlsx", ".xlsm"):
            sources.append(f"{name}: Excel workbook")
            return xlsx_to_text(data)
        if ext == ".xls" or ext in (".doc", ".ppt"):
            warnings.append(f"{name}: old Office format. Open it and save as {'.xlsx' if ext == '.xls' else '.docx'}, or paste the content.")
            return ""
        if ext == ".pdf":
            sources.append(f"{name}: PDF")
            text = pdf_to_text(data)
            if len(text.strip()) < 20:
                warnings.append(f"{name}: the PDF has no readable text (probably a scan). Paste the content by hand.")
            return text
        if ext == ".rtf":
            sources.append(f"{name}: Rich Text")
            return rtf_to_text(decode(data))
        if ext in (".html", ".htm", ".xhtml"):
            sources.append(f"{name}: web page / HTML mail")
            return html_to_text(decode(data))
        if ext == ".zip":
            return _read_zip(name, data, depth, warnings, sources)
        if ext in IMAGE_TYPES:
            warnings.append(f"{name}: images cannot be read yet. Type or paste what the image says.")
            return ""
        # Anything else: plain text if it looks like text, sniffing for formats with a wrong or missing extension.
        if data[:2] == b"PK":
            return _read_zip(name, data, depth, warnings, sources)
        if data[:5] == b"%PDF-":
            return _read(name + ".pdf", data, depth, warnings, sources)
        if data[:5] == b"{\\rtf":
            return _read(name + ".rtf", data, depth, warnings, sources)
        if b"\x00" in data[:2000] and not data.startswith((b"\xff\xfe", b"\xfe\xff")) and data[1:2] != b"\x00":
            warnings.append(f"{name}: not a file type we can read. Paste the content instead.")
            return ""
        text = decode(data)
        if re.match(r"\s*<(!doctype html|html)", text[:200], re.I):
            sources.append(f"{name}: web page / HTML mail")
            return html_to_text(text)
        sources.append(f"{name}: " + ("chat log" if looks_like_chat(clean(text)) else "text"))
        return text
    except Exception as e:  # a damaged or protected file must not stop the others
        warnings.append(f"{name}: could not be read ({type(e).__name__}: {e}). Paste its content instead.")
        return ""


def _mbox_messages(data: bytes) -> list[bytes]:
    """The mailbox module only reads from a path, so go through a temporary file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "box.mbox"
        path.write_bytes(data)
        box = mailbox.mbox(str(path))
        try:
            return [m.as_bytes() for m in box]
        finally:
            box.close()


def _attachment_text(eml: bytes, name: str, warnings: list[str]) -> str:
    """Text of readable files attached to an .eml, so a quantity hidden in an attachment is not missed."""
    from email import policy
    from email.parser import BytesParser
    out = []
    msg = BytesParser(policy=policy.default).parsebytes(eml)
    for part in msg.iter_attachments():
        att_name, payload = part.get_filename(), part.get_payload(decode=True)
        if not att_name or not payload:
            continue
        sub_w, sub_s = [], []
        text = _read(att_name, payload, MAX_ZIP_DEPTH, sub_w, sub_s).strip()
        if text:
            out.append(f"\n\n----- Attachment: {att_name} -----\n{text}")
        warnings += [f"{name} → {w}" for w in sub_w if "not a file type" not in w]
    return "".join(out)


def _read_zip(name: str, data: bytes, depth: int, warnings: list[str], sources: list[str]) -> str:
    if depth >= MAX_ZIP_DEPTH:
        warnings.append(f"{name}: archive inside archive, not opened.")
        return ""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        warnings.append(f"{name}: not a valid archive.")
        return ""
    members = [i for i in z.infolist() if not i.is_dir() and not Path(i.filename).name.startswith(("._", "."))
               and "__MACOSX" not in i.filename]
    if any(i.flag_bits & 1 for i in members):
        warnings.append(f"{name}: the archive is password-protected. Unzip it and upload the files.")
        return ""
    sources.append(f"{name}: archive with {len(members)} file(s)")
    if len(members) > MAX_ZIP_FILES:
        warnings.append(f"{name}: only the first {MAX_ZIP_FILES} of {len(members)} files were read.")
    sections = []
    for info in members[:MAX_ZIP_FILES]:
        if info.file_size > 50_000_000:
            warnings.append(f"{info.filename}: too large, skipped.")
            continue
        text = _read(info.filename, z.read(info), depth + 1, warnings, sources).strip()
        if text:
            sections.append(f"----- {info.filename} -----\n{text}")
    return "\n\n".join(sections)


# ---------- public entry points ----------

def ingest(files: list[tuple[str, bytes]], case_id: str, pasted: str = "") -> Ingested:
    """Combine uploaded files (and optionally pasted text) into one inquiry."""
    warnings, sources, sections = [], [], []
    for name, data in files:
        text = clean(_read(name, data, 0, warnings, sources))
        if len(text) > MAX_CHARS:
            warnings.append(f"{name}: very long, only the first {MAX_CHARS:,} characters were read.")
            text = text[:MAX_CHARS]
        if text:
            sections.append((name, text))
    if pasted.strip():
        sections.append(("pasted text", clean(pasted)))
        sources.append("pasted text")

    if not sections:
        text = ""
    elif len(sections) == 1:
        text = sections[0][1]
    else:  # label each part so the reader (and the evidence check) can tell where text comes from
        text = "\n\n".join(f"===== {n} =====\n{t}" for n, t in sections)
    email = parse_email_text(text, case_id)
    if email.headers and len(sections) > 1:  # the header block belongs to the first email; keep it on top
        email = parse_email_text(re.sub(r"^===== .* =====\n", "", text, count=1), case_id)
    if not text:
        warnings.append("Nothing readable was found in the input.")
    return Ingested(email=email, warnings=warnings, sources=sources)
