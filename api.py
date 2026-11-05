"""Backend for the Quote Assistant web interface. All the logic lives in quotetool/; this only exposes it.

Start it with:  uvicorn api:app --port 8000      (after building the interface once: cd web && npm run build)
For interface development:  uvicorn api:app --reload  and, in web/,  npm run dev
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import quotetool as qt
from quotetool import llm, report
from quotetool.extract import cache_path
from quotetool.history import load_history
from quotetool.ingest import ingest
from quotetool.matching import customer_issues, match_customer, match_issues, match_items
from quotetool.quotedoc import build_quote

ROOT = Path(__file__).parent
INBOX, CACHE, RAW = ROOT / "data/inbox", ROOT / "data/lake/processed", ROOT / "data/lake/raw"
HISTORY_FILE, EXAMPLE_HISTORY_FILE = ROOT / "data/history/past_quotes.csv", ROOT / "examples/past_quotes_example.csv"
DIST = ROOT / "web/dist"

app = FastAPI(title="Quote Assistant")
RESULTS: dict[str, qt.checks.CheckResult] = {}   # last results, so the quotation can be built from them


def _history() -> tuple[list[dict], dict]:
    path = HISTORY_FILE if HISTORY_FILE.exists() else EXAMPLE_HISTORY_FILE
    try:
        rows, error = load_history(path), None
    except Exception as e:
        rows, error = [], str(e)
    return rows, {"count": len(rows), "file": path.name, "is_example": path != HISTORY_FILE, "error": error}


def _field(f) -> dict:
    return {"value": f.value, "status": f.status.value, "note": f.note, "evidence": f.evidence}


def _json(data) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(data, default=str)))


@app.get("/api/status")
def status(mode: str = "ai", model: str = "qwen3.5:9b"):
    _, hist = _history()
    ok, message = (llm.check(qt.LLMConfig(model=model)) if mode == "ai" else (True, "Rules only: no language model used"))
    return {"model": {"ok": ok, "message": message}, "history": hist,
            "samples": sorted(p.stem for p in INBOX.glob("*.txt")) if INBOX.exists() else []}


@app.post("/api/analyze")
def analyze(files: list[UploadFile] = File(default=[]), pasted: str = Form(""), sample: str = Form(""),
            mode: str = Form("ai"), model: str = Form("qwen3.5:9b")):
    warnings, sources = [], []
    if sample:
        email = qt.load_inbox(INBOX).get(sample)
        if email is None:
            raise HTTPException(404, f"Unknown sample {sample!r}")
    else:
        blobs = [(f.filename or "file", f.file.read()) for f in files]
        digest = hashlib.sha1(b"".join(d for _, d in blobs) + pasted.encode()).hexdigest()[:8]
        stem = Path(blobs[0][0]).stem if blobs else "pasted"
        got = ingest(blobs, f"{stem}-{digest}", pasted=pasted)
        email, warnings, sources = got.email, got.warnings, got.sources
    if not email.text.strip():
        return _json({"error": "Nothing readable was found in the input.", "warnings": warnings, "sources": sources})

    config = qt.LLMConfig(model=model)
    saved = mode == "ai" and cache_path(email, config, CACHE).exists()
    try:
        extraction = qt.extract_llm(email, config, cache_dir=CACHE) if mode == "ai" else qt.extract_baseline(email)
    except Exception as e:  # model not running, or an answer that cannot be read
        return _json({"error": f"The model could not read this inquiry: {e}. Try again, or switch to Rules only.",
                      "warnings": warnings, "sources": sources})

    history, hist = _history()
    result = qt.check(extraction, email)
    customer = result.extraction.header["customer"].value
    match_items(result.extraction.items, history)
    match_customer(result.extraction.items, history, customer)
    result.issues += match_issues(result.extraction.items) + customer_issues(result.extraction.items, customer)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{email.case_id}.txt").write_text(email.text, encoding="utf-8")
    RESULTS[email.case_id] = result

    ex = result.extraction
    counts = {s: sum(i.severity == s for i in result.issues) for s in ("blocking", "check", "assumption", "info")}
    return _json({
        "case_id": email.case_id, "text": email.text, "sources": sources, "warnings": warnings, "saved": saved,
        "ready": result.ready_to_quote, "counts": counts, "history": hist,
        "header": [{"name": k, **_field(f)} for k, f in ex.header.items()],
        "items": [{k: _field(f) for k, f in item.items()} for item in ex.items],
        "issues": [vars(i) for i in sorted(result.issues, key=lambda i: ("blocking", "check", "assumption", "info").index(i.severity))],
        "client_email": result.client_email,
        "evidence": report.evidence_table(ex).to_dict("records"),
    })


class QuoteRequest(BaseModel):
    case_id: str
    prices: list[float | None]
    company: str = "[Company name]"


@app.post("/api/quotation")
def quotation(req: QuoteRequest):
    result = RESULTS.get(req.case_id)
    if result is None:
        raise HTTPException(404, "This inquiry is no longer in memory. Read it again, then create the quotation.")
    try:
        data = build_quote(result, req.prices, req.company)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="quotation_{req.case_id}.docx"'})


if DIST.exists():  # the built interface
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = DIST / path
        return FileResponse(target if path and target.is_file() else DIST / "index.html")
