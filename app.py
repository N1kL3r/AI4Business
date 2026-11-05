"""Quote Assistant: drop in a customer inquiry, get a checked quote draft.

Start it with:  streamlit run app.py
"""
import hashlib
import html
from pathlib import Path

import pandas as pd
import streamlit as st

import quotetool as qt
from quotetool import llm, report
from quotetool.emails import parse_email_text
from quotetool.extract import cache_path
from quotetool.history import load_history
from quotetool.ingest import ingest
from quotetool.matching import customer_issues, match_customer, match_issues, match_items
from quotetool.quotedoc import build_quote
from quotetool.schema import Status

ROOT = Path(__file__).parent
INBOX, CACHE, RAW = ROOT / "data/inbox", ROOT / "data/lake/processed", ROOT / "data/lake/raw"
AI, RULES = "Language model (local)", "Rules only (no AI)"
SEVERITY = {"blocking": ("Blocking", "bad"), "check": ("Check", "warn"),
            "assumption": ("Assumption", "info"), "info": ("Note", "mute")}
STATUS_CLASS = {Status.FOUND: "", Status.MISSING: "bad", Status.NEEDS_REVIEW: "warn", Status.INFERRED: "info"}
TIER_LABEL = {"exact": ("Same part number", "ok"), "similar": ("Similar part", "warn"), "none": ("No match", "mute")}

# Past quotes the parts are compared against. Put the company's real export at data/history/past_quotes.csv
# (columns: part_number, description, price); until then the made-up example file is used.
HISTORY_FILE, EXAMPLE_HISTORY_FILE = ROOT / "data/history/past_quotes.csv", ROOT / "examples/past_quotes_example.csv"

st.set_page_config(page_title="Quote Assistant", page_icon=":material/precision_manufacturing:", layout="wide")

STYLE = """
<style>
:root { --ink:#1F2430; --muted:#687082; --line:#E1E4EA; --panel:#F5F7FA; --charcoal:#15161B; --blue:#0078D2;
        --blue-dark:#005FA8; --blue-tint:#E6F1FC; --lime:#86BC25;
        --ok:#1B7A43; --bad:#B42318; --warn:#9A6700; --info:#0B5CAD;
        --mono: ui-monospace,"SF Mono","IBM Plex Mono",Menlo,Consolas,monospace; }
html, body, [class*="css"], .stApp { font-family: "Helvetica Neue",Helvetica,Arial,sans-serif; color: var(--ink); }
.stApp { background: #fff; }
header[data-testid="stHeader"] { display: none; }
.block-container { padding: 0 2.5rem 3rem; max-width: 1280px; }
section[data-testid="stSidebar"] { background: var(--panel); border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] .block-container { padding: 1.5rem 1.25rem; }

/* header + hero */
.nav { background: var(--charcoal); margin: 0 -2.5rem; padding: .85rem 2.5rem; display: flex; align-items: center;
       justify-content: space-between; }
.nav .brand { color: #fff; font-weight: 800; letter-spacing: .14em; font-size: .95rem; text-transform: uppercase; }
.nav .brand i { display: inline-block; width: .7rem; height: .7rem; background: var(--blue); margin-right: .7rem; }
.nav .links { color: #A9B0BE; font-size: .74rem; letter-spacing: .1em; text-transform: uppercase; display: flex; gap: 1.8rem; }
.hero { margin: 0 -2.5rem 0; padding: 3rem 2.5rem 0; color: #fff; background-color: var(--charcoal);
        background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px),
                          linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px);
        background-size: 32px 32px; border-bottom: 4px solid var(--blue); }
.hero .tag { color: var(--lime); font-size: .75rem; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
.hero h1 { color: #fff; font-size: 2.7rem; line-height: 1.08; font-weight: 800; letter-spacing: -.02em;
           max-width: 46rem; margin: .7rem 0 .9rem; padding: 0; }
.hero h1 b { color: var(--blue); background: none; }
.hero p { color: #C3C9D5; max-width: 40rem; font-size: 1.02rem; line-height: 1.55; margin-bottom: 2.2rem; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid rgba(255,255,255,.18); }
.stat { padding: 1.1rem 1.4rem 1.3rem 0; }
.stat + .stat { padding-left: 1.4rem; border-left: 1px solid rgba(255,255,255,.18); }
.stat .v { font-size: 1.9rem; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums; }
.stat .l { font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: #A9B0BE; margin-top: .15rem; }

/* process steps */
.steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; margin: 2rem 0 .5rem; border: 1px solid var(--line); }
.step { padding: .9rem 1.2rem; background: #fff; display: flex; gap: .9rem; align-items: center; }
.step + .step { border-left: 1px solid var(--line); }
.step .n { width: 1.9rem; height: 1.9rem; display: grid; place-items: center; font-weight: 800; font-size: .85rem;
           background: var(--panel); color: var(--muted); border: 1px solid var(--line); }
.step .t { font-weight: 700; font-size: .9rem; } .step .d { font-size: .76rem; color: var(--muted); }
.step.on { background: var(--blue-tint); box-shadow: inset 0 -3px 0 var(--blue); }
.step.on .n { background: var(--blue); border-color: var(--blue); color: #fff; }
.step.done .n { background: var(--ink); border-color: var(--ink); color: #fff; }

h2, h3 { font-weight: 800; letter-spacing: -.01em; }
.eyebrow { font-size: .74rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; color: var(--ink);
           margin: 2rem 0 .7rem; padding-bottom: .5rem; border-bottom: 2px solid var(--ink); }

/* verdict */
.verdict { background: var(--ok); color: #fff; padding: 1.4rem 1.8rem; margin: .5rem 0 0; display: flex;
           align-items: center; gap: 1.6rem; }
.verdict.stop { background: var(--bad); }
.verdict .flag { font-size: .72rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase;
                 border: 2px solid rgba(255,255,255,.7); padding: .35rem .7rem; white-space: nowrap; }
.verdict .title { font-size: 1.35rem; font-weight: 800; letter-spacing: -.01em; }
.verdict .sub { color: rgba(255,255,255,.88); margin-top: .15rem; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); border-top: 0; margin-bottom: 1.6rem; }
.kpi { background: var(--panel); padding: 1rem 1.4rem; }
.kpi + .kpi { border-left: 1px solid var(--line); }
.kpi .v { font-size: 2rem; font-weight: 800; font-variant-numeric: tabular-nums; line-height: 1.05; }
.kpi .l { font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-top: .3rem; font-weight: 700; }

/* facts */
.facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0 2rem; background: var(--panel);
         border: 1px solid var(--line); border-top: 3px solid var(--blue); padding: .6rem 1.6rem; }
.fact { padding: .7rem 0; border-bottom: 1px solid var(--line); }
.fact .l { font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.fact .v { font-size: 1rem; margin-top: .15rem; font-weight: 500; }
.fact .v.bad { color: var(--bad); } .fact .v.warn { color: var(--warn); } .fact .v.info { color: var(--info); }
.fact .v.empty { color: #98A2B0; font-weight: 400; }

/* tables */
table.grid { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid var(--line);
             border-top: 3px solid var(--charcoal); font-size: .88rem; }
table.grid th { text-align: left; background: var(--panel); color: var(--ink); font-size: .68rem; letter-spacing: .12em;
                text-transform: uppercase; font-weight: 800; padding: .7rem .9rem; border-bottom: 1px solid var(--line); }
table.grid td { padding: .7rem .9rem; border-bottom: 1px solid var(--line); vertical-align: top; }
table.grid tr:hover td { background: #FAFBFD; }
table.grid tr:last-child td { border-bottom: 0; }
table.grid td.mono { font-family: var(--mono); font-size: .84rem; letter-spacing: -.01em; }
table.grid td.bad { background: #FDECEA; color: var(--bad); font-weight: 600; }
table.grid td.warn { background: #FFF6DB; color: var(--warn); font-weight: 600; }
table.grid td.info { background: var(--blue-tint); color: var(--info); font-weight: 600; }
table.grid td.num { font-variant-numeric: tabular-nums; text-align: right; }
.wrap { overflow-x: auto; }

.badge { display: inline-block; font-size: .66rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;
         padding: .2rem .55rem; border-radius: 2px; white-space: nowrap; }
.badge.ok { color: #fff; background: var(--ok); } .badge.bad { color: #fff; background: var(--bad); }
.badge.warn { color: #3A2A00; background: #F1BA2B; } .badge.info { color: #fff; background: var(--blue); }
.badge.mute { color: var(--muted); background: var(--panel); border: 1px solid var(--line); }
.legend { font-size: .78rem; color: var(--muted); margin-top: .7rem; display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }

/* sidebar status */
.status { font-size: .84rem; line-height: 1.45; padding: .6rem .8rem; border: 1px solid var(--line);
          border-left: 4px solid var(--lime); margin-bottom: .6rem; background: #fff; }
.status.warn { border-left-color: #F1BA2B; }
.status b { display: block; font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.srcnote { font-size: .8rem; color: var(--muted); margin: .25rem 0; font-family: var(--mono); }

/* controls */
button[kind="primary"], div[data-testid="stDownloadButton"] button { background: var(--blue); color: #fff; border: 0;
        border-radius: 2px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; font-size: .8rem; padding: .65rem 1.4rem; }
button[kind="primary"]:hover, div[data-testid="stDownloadButton"] button:hover { background: var(--blue-dark); color: #fff; }
button[data-baseweb="tab"] { font-weight: 700; text-transform: uppercase; letter-spacing: .08em; font-size: .75rem; }
div[data-baseweb="tab-highlight"] { background: var(--blue) !important; height: 3px !important; }
div[data-testid="stFileUploader"] section { background: var(--panel); border: 2px dashed #B7BECB; border-radius: 2px; padding: 1.4rem; }
div[data-testid="stFileUploader"] section button { border-radius: 2px; }
.trust { margin: 3rem -2.5rem -3rem; padding: 1.4rem 2.5rem; background: var(--panel); border-top: 1px solid var(--line);
         display: flex; gap: 2.5rem; flex-wrap: wrap; font-size: .72rem; letter-spacing: .12em; text-transform: uppercase;
         color: var(--muted); font-weight: 700; }
.trust span::before { content: ""; display: inline-block; width: .5rem; height: .5rem; background: var(--lime); margin-right: .6rem; }
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


# ---------- helpers ----------
@st.cache_data
def read_history(path: str, modified: float) -> list[dict]:  # `modified` makes the cache refresh when the file changes
    return load_history(path)


def short_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


def label(field_name: str) -> str:
    return field_name.replace("_", " ").capitalize()


def esc(value) -> str:
    return html.escape(report._show(value))


def badge(text: str, kind: str) -> str:
    return f'<span class="badge {kind}">{html.escape(text)}</span>'


def table(columns: list[str], rows: list[list], classes: list[list[str]] | None = None, mono: tuple = ()) -> str:
    """HTML table. Cells are escaped here unless they are already badges (start with '<span')."""
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = ""
    for r, row in enumerate(rows):
        cells = ""
        for c, cell in enumerate(row):
            text = cell if isinstance(cell, str) and cell.startswith("<span") else esc(cell)
            cls = (classes[r][c] if classes else "") + (" mono" if columns[c] in mono else "")
            cells += f'<td class="{cls}">{text or "—"}</td>'
        body += f"<tr>{cells}</tr>"
    return f'<div class="wrap"><table class="grid"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def steps(active: int) -> None:
    names = [("Inquiry", "Upload or paste"), ("Read", "Extract and check"), ("Review", "Parts and past quotes"),
             ("Quotation", "Price and sign")]
    out = ""
    for n, (t, d) in enumerate(names, 1):
        cls = "on" if n == active else ("done" if n < active else "")
        out += f'<div class="step {cls}"><div class="n">{n}</div><div><div class="t">{t}</div><div class="d">{d}</div></div></div>'
    st.markdown(f'<div class="steps">{out}</div>', unsafe_allow_html=True)


def eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------- settings ----------
with st.sidebar:
    st.markdown('<div class="eyebrow" style="margin-top:0">Settings</div>', unsafe_allow_html=True)
    mode = st.radio("Reader", [AI, RULES], key="reader",
                    help="The language model reads the email and fills in the quote template. "
                         "'Rules only' uses fixed patterns, no AI: faster, but only for familiar layouts.")
    model = st.text_input("Model", "qwen3.5:9b", disabled=mode != AI)
    config = qt.LLMConfig(model=model)
    if mode == AI:
        ok, message = llm.check(config)
        kind = "ok" if ok else "warn"
        extra = "" if ok else "<br>Inquiries read before still open from their saved answers. For new ones, start the model or switch to Rules only."
        st.markdown(f'<div class="status {kind}"><b>Language model</b>{html.escape(message)}{extra}</div>',
                    unsafe_allow_html=True)
    history_file = HISTORY_FILE if HISTORY_FILE.exists() else EXAMPLE_HISTORY_FILE
    try:
        history = read_history(str(history_file), history_file.stat().st_mtime)
    except Exception as e:
        history = []
        st.markdown(f'<div class="status warn"><b>Past quotes</b>Could not read {html.escape(history_file.name)}: '
                    f'{html.escape(str(e))}. No reference prices will be shown.</div>', unsafe_allow_html=True)
    else:
        if history_file == HISTORY_FILE:
            st.markdown(f'<div class="status ok"><b>Past quotes</b>{len(history)} loaded</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status warn"><b>Past quotes</b>{len(history)} example records (made up). '
                        'Reference prices are not real. Put the real export at data/history/past_quotes.csv.</div>',
                        unsafe_allow_html=True)
    st.caption("Everything runs on this computer. Nothing is sent anywhere. "
               "Answers are saved in data/lake/, so an inquiry read once opens instantly next time.")

# ---------- header and input ----------
st.markdown(
    '<div class="nav"><div class="brand"><i></i>Quote Assistant</div>'
    '<div class="links"><span>Runs on this computer</span><span>Evidence for every value</span>'
    '<span>Human sign-off</span></div></div>'
    '<div class="hero"><div class="tag">Quotation desk</div>'
    '<h1>Find your own past. <b>Quote with confidence.</b></h1>'
    '<p>Drop in a customer inquiry in any form. The tool reads it, compares every part with past quotes, '
    'shows exactly what is missing and drafts the question to the customer. A person always signs the quote.</p>'
    f'<div class="stats"><div class="stat"><div class="v">{len(history):,}</div><div class="l">Past quotes in archive</div></div>'
    '<div class="stat"><div class="v">14</div><div class="l">File types accepted</div></div>'
    f'<div class="stat"><div class="v">{"AI" if mode == AI else "Rules"}</div><div class="l">Reader in use</div></div>'
    '<div class="stat"><div class="v">100%</div><div class="l">Processed locally</div></div></div></div>',
    unsafe_allow_html=True)
_state = st.session_state
steps(4 if _state.get("result") is not None and _state["result"].ready_to_quote else
      3 if _state.get("result") is not None else 1)

eyebrow("1 · Inquiry")
source = st.radio("Source", ["Upload files", "Paste text", "Sample inquiries"], horizontal=True, key="source",
                  label_visibility="collapsed")
email, warnings, sources = None, [], []
if source == "Upload files":
    uploads = st.file_uploader(
        "Emails (.eml, .msg), chat exports (WhatsApp, Teams, Slack), Word, Excel, PDF, text, HTML, ZIP. "
        "Several files are read together as one inquiry.", accept_multiple_files=True)
    if uploads:
        blobs = [(u.name, u.getvalue()) for u in uploads]
        digest = short_hash(b"".join(d for _, d in blobs))
        got = ingest(blobs, f"{Path(blobs[0][0]).stem}-{digest}")
        email, warnings, sources = got.email, got.warnings, got.sources
elif source == "Paste text":
    text = st.text_area("Paste the inquiry: email, chat conversation or notes (From/Date/Subject lines are optional)",
                        height=220)
    if text.strip():
        got = ingest([], f"pasted-{short_hash(text.encode())}", pasted=text)
        email, warnings, sources = got.email, got.warnings, got.sources
else:
    samples = qt.load_inbox(INBOX) if INBOX.exists() else {}
    if samples:
        email = samples[st.selectbox("Sample", list(samples))]
    else:
        st.info("No sample inquiries found in data/inbox/.")

for line in sources:
    st.markdown(f'<div class="srcnote">Recognised: {html.escape(line)}</div>', unsafe_allow_html=True)
for w in warnings:
    st.warning(w)
if email is None or not email.text.strip():
    st.stop()

with st.expander("Text as read by the tool", expanded=False):
    st.text(email.text)

# ---------- run ----------
run_key = (email.case_id, mode, model)
if st.button("Read inquiry", type="primary") or st.session_state.get("last_run") == run_key:
    if st.session_state.get("last_run") != run_key:
        saved = mode == AI and cache_path(email, config, CACHE).exists()
        with st.spinner("Reading the inquiry. With the language model this can take a minute."):
            try:
                extraction = qt.extract_llm(email, config, cache_dir=CACHE) if mode == AI else qt.extract_baseline(email)
            except Exception as e:  # model not running, or an answer that cannot be read
                st.error(f"The model could not read this inquiry: {e}\n\nTry again, or switch to Rules only.")
                st.stop()
        result = qt.check(extraction, email)
        match_items(result.extraction.items, history)
        match_customer(result.extraction.items, history, result.extraction.header["customer"].value)
        result.issues += match_issues(result.extraction.items) + customer_issues(
            result.extraction.items, result.extraction.header["customer"].value)
        RAW.mkdir(parents=True, exist_ok=True)
        (RAW / f"{email.case_id}.txt").write_text(email.text, encoding="utf-8")  # raw layer of the data lake
        st.session_state.update(last_run=run_key, result=result, saved=saved)
else:
    st.stop()

result, saved = st.session_state["result"], st.session_state["saved"]
ex = result.extraction
counts = {s: sum(i.severity == s for i in result.issues) for s in SEVERITY}

eyebrow("2 · Result")
if saved:
    st.caption("Using the saved answer for this inquiry (data/lake/processed).")

if result.ready_to_quote:
    st.markdown('<div class="verdict"><div class="flag">Ready</div><div><div class="title">Ready for pricing</div>'
                '<div class="sub">Nothing essential is missing. Review the checks before a price is set.</div></div></div>',
                unsafe_allow_html=True)
else:
    st.markdown(f'<div class="verdict stop"><div class="flag">On hold</div><div><div class="title">Information required before quoting</div>'
                f'<div class="sub">{counts["blocking"]} essential item(s) missing. A draft reply to the customer is in the '
                'Customer reply tab.</div></div></div>', unsafe_allow_html=True)
st.markdown('<div class="kpis">' + "".join(
    f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>'
    for v, l in [(len(ex.items), "Parts"), (counts["blocking"], "Missing, blocking"),
                 (counts["check"], "To check"), (counts["assumption"], "Assumptions")]) + "</div>",
    unsafe_allow_html=True)

tab_inquiry, tab_parts, tab_past, tab_issues, tab_quote, tab_reply, tab_evidence = st.tabs(
    ["Inquiry", "Parts", "Past quotes", "Review items", "Quotation", "Customer reply", "Evidence"])

with tab_inquiry:
    facts = ""
    for name, f in ex.header.items():
        cls = STATUS_CLASS[f.status] or ("empty" if f.value in (None, "", []) else "")
        facts += (f'<div class="fact"><div class="l">{html.escape(label(name))}</div>'
                  f'<div class="v {cls}">{esc(f.value) or "Not stated"}</div></div>')
    st.markdown(f'<div class="facts">{facts}</div>', unsafe_allow_html=True)
    st.markdown('<div class="legend">Colour key: ' + badge("Check", "warn") + badge("Missing", "bad")
                + badge("Assumed by us", "info") + ' &nbsp;Uncoloured values were stated in the inquiry.</div>',
                unsafe_allow_html=True)

with tab_parts:
    fields = ("part_number", "description", "quantity", "unit", "pieces_per_unit", "material", "drawing_ref",
              "machine_model", "match_tier", "reference_price", "customer_price")
    rows, classes = [], []
    for item in ex.items:
        row, cls = [], []
        for k in fields:
            f = item[k]
            if k == "match_tier":
                text, kind = TIER_LABEL.get(f.value, ("", "mute"))
                row.append(badge(text, kind)); cls.append("")
            else:
                row.append("Not stated" if f.status == Status.MISSING and k in qt.checks.BLOCKING_LINE_FIELDS else f.value)
                cls.append(STATUS_CLASS[f.status] + (" num" if k in ("quantity", "pieces_per_unit", "reference_price", "customer_price") else ""))
        rows.append(row); classes.append(cls)
        cls[0] += " mono"; cls[6] += " mono"
    if rows:
        st.markdown(table([{"match_tier": "Past quote match", "customer_price": "Last price, this customer"}.get(k, label(k))
                               for k in fields], rows, classes),
                    unsafe_allow_html=True)
    else:
        st.write("No parts were found.")
    st.markdown('<div class="legend">' + badge("Check", "warn") + badge("Missing", "bad") + badge("Assumed", "info")
                + ' &nbsp;Reference price is the latest past quote of the same part, or of a similar part when marked so.</div>',
                unsafe_allow_html=True)

with tab_past:
    tiers = [item["match_tier"].value for item in ex.items]
    st.write(f"Compared with **{len(history)} past quotes** in `{history_file.relative_to(ROOT)}`: "
             f"**{tiers.count('exact')}** part(s) quoted before with the same part number, "
             f"**{tiers.count('similar')}** only with a similar description (check), "
             f"**{tiers.count('none')}** not found.")
    past = [[item["part_number"].value, TIER_LABEL[item["match_tier"].value][0], q["part_number"], q["description"],
             q["price"], q["currency"], q["quantity"], q["quoted_date"], q["customer"], q["quote_id"],
             q["similarity"], q["source_row"]]
            for item in ex.items for q in item["past_quotes"].value]
    if past:
        cols = ["Part in inquiry", "Match", "Past part number", "Past description", "Price", "Currency", "Quantity",
                "Quoted on", "Customer", "Quote id", "Similarity", "Row in file"]
        st.markdown(table(cols, past, mono=("Part in inquiry", "Past part number", "Quote id")), unsafe_allow_html=True)
        st.caption("Newest first. 'Row in file' is the row in the past-quotes file, so the original quote can be looked up. "
                   "A similar match is a different part: its price is only a pointer.")
    else:
        st.write("No past quotes found for any part.")

with tab_issues:
    issues = report.issues_table(result)
    if issues.empty:
        st.write("Nothing needs attention.")
    else:
        rows = [[r.where, label(r.field), badge(*SEVERITY[r.severity]), r.message] for r in issues.itertuples()]
        st.markdown(table(["Where", "Field", "Severity", "Message"], rows), unsafe_allow_html=True)

with tab_quote:
    if not result.ready_to_quote:
        st.write("The quotation can be prepared once the missing information is in. See Review items and Customer reply.")
    else:
        st.caption("Set the unit price per line. The suggestion is the last price quoted to this customer for the same part, "
                   "else the latest past price of that part. The price is your decision; the tool never sets it.")
        suggestion = lambda item: item["customer_price"].value if item["customer_price"].value is not None else (
            item["reference_price"].value if item["match_tier"].value == "exact" else None)
        lines = pd.DataFrame([{"Part": item["part_number"].value, "Qty": item["quantity"].value,
                               "Unit price": suggestion(item),
                               "Basis": "Last price to this customer" if item["customer_price"].value is not None
                               else ("Latest past price" if item["match_tier"].value == "exact" else "No reference")}
                              for item in ex.items])
        edited = st.data_editor(lines, hide_index=True, width="stretch", disabled=["Part", "Qty", "Basis"],
                                key=f"prices-{email.case_id}")
        prices = [None if pd.isna(p) else float(p) for p in edited["Unit price"]]
        company = st.text_input("Company name on the quotation", "[Company name]")
        try:
            docx_bytes = build_quote(result, prices, company)
        except RuntimeError as e:
            st.warning(str(e))
        else:
            st.download_button("Download quotation (.docx)", docx_bytes, file_name=f"quotation_{email.case_id}.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               type="primary")
        st.caption("Opens in Word for editing. It carries a signature line and is not valid until a person signs it.")

with tab_reply:
    if result.client_email:
        reply = st.text_area("Edit before sending", result.client_email, height=280)
        st.download_button("Download reply (.txt)", reply, file_name=f"reply_{email.case_id}.txt")
    else:
        st.write("Nothing essential is missing, so there is no need to ask the customer.")

with tab_evidence:
    st.caption("Every value with the exact text it was taken from.")
    st.dataframe(report.evidence_table(ex).rename(columns=label), hide_index=True, width="stretch")

st.markdown('<div class="trust"><span>Processed locally</span><span>Every value traced to its source text</span>'
            '<span>Past prices traced to the original quote</span><span>Signed by a person before sending</span></div>',
            unsafe_allow_html=True)
