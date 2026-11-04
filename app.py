"""Quote Assistant: drop in a customer inquiry, get a checked quote draft.

Start it with:  streamlit run app.py
"""
import hashlib
from pathlib import Path

import streamlit as st

import quotetool as qt
from quotetool import llm, report
from quotetool.emails import parse_email_text, parse_eml
from quotetool.extract import cache_path
from quotetool.history import load_history
from quotetool.matching import match_items

ROOT = Path(__file__).parent
INBOX, CACHE, RAW = ROOT / "data/inbox", ROOT / "data/lake/processed", ROOT / "data/lake/raw"
AI, RULES = "AI model (Ollama)", "Rules only (no AI)"
SEVERITY_ICONS = {"blocking": "🛑 blocking", "check": "⚠️ check", "assumption": "🔵 assumption", "info": "ℹ️ info"}

# Past quotes the parts are compared against. Put the company's real export at data/history/past_quotes.csv
# (columns: part_number, description, price); until then the made-up example file is used.
HISTORY_FILE, EXAMPLE_HISTORY_FILE = ROOT / "data/history/past_quotes.csv", ROOT / "examples/past_quotes_example.csv"

st.set_page_config(page_title="Quote Assistant", page_icon="📨", layout="wide")


@st.cache_data
def read_history(path: str, modified: float) -> list[dict]:  # `modified` makes the cache refresh when the file changes
    return load_history(path)


def short_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


def label(field_name: str) -> str:
    return field_name.replace("_", " ").capitalize()


# ---------- Settings ----------
with st.sidebar:
    st.header("Settings")
    mode = st.radio("Who reads the email?", [AI, RULES], key="reader")
    model = st.text_input("Model", "qwen3.5:9b", disabled=mode != AI)
    config = qt.LLMConfig(model=model)
    if mode == AI:
        ok, message = llm.check(config)
        if ok:
            st.success(message)
        else:
            st.warning(f"{message}\n\nEmails read before still open from their saved answers. "
                       "For new emails, start the model or switch to 'Rules only'.")
    history_file = HISTORY_FILE if HISTORY_FILE.exists() else EXAMPLE_HISTORY_FILE
    try:
        history = read_history(str(history_file), history_file.stat().st_mtime)
    except Exception as e:
        history = []
        st.warning(f"Could not read the past quotes in {history_file.name}: {e}\n\nNo reference prices will be shown.")
    else:
        if history_file == HISTORY_FILE:
            st.success(f"{len(history)} past quotes loaded")
        else:
            st.warning(f"{len(history)} EXAMPLE past quotes (made up). Reference prices are not real. "
                       "Put the real export at data/history/past_quotes.csv.")
    st.caption("Everything runs on this computer: the email is not sent anywhere. "
               "Answers are saved in data/lake/, so an email read once opens instantly next time.")

# ---------- Input ----------
st.title("📨 Quote Assistant")
st.write("Drop in a customer inquiry. The tool fills in the quote template, shows what is missing, "
         "and drafts a reply asking the customer for it. **A person always checks before anything is sent.**")

source = st.radio("Email", ["Upload a file", "Paste text", "Sample emails"], horizontal=True, key="source",
                  label_visibility="collapsed")
email = None
if source == "Upload a file":
    upload = st.file_uploader("Drop an email here (.eml from your mail program, or .txt)", type=["eml", "txt"])
    if upload:
        data = upload.getvalue()
        case_id = f"{Path(upload.name).stem}-{short_hash(data)}"
        email = (parse_eml(data, case_id) if upload.name.lower().endswith(".eml")
                 else parse_email_text(data.decode("utf-8", errors="replace"), case_id))
elif source == "Paste text":
    text = st.text_area("Paste the email (with From/Date/Subject lines if you have them)", height=220)
    if text.strip():
        email = parse_email_text(text, f"pasted-{short_hash(text.encode())}")
else:
    samples = qt.load_inbox(INBOX) if INBOX.exists() else {}
    if samples:
        email = samples[st.selectbox("Sample", list(samples))]
    else:
        st.info("No sample emails found in data/inbox/.")

if email is None:
    st.stop()

with st.expander("Original email", expanded=False):
    st.text(email.text)

# ---------- Run ----------
run_key = (email.case_id, mode, model)
if st.button("Read email", type="primary") or st.session_state.get("last_run") == run_key:
    if st.session_state.get("last_run") != run_key:
        saved = mode == AI and cache_path(email, config, CACHE).exists()
        with st.spinner("Reading the email. With the AI model this can take a minute…"):
            try:
                extraction = qt.extract_llm(email, config, cache_dir=CACHE) if mode == AI else qt.extract_baseline(email)
            except Exception as e:  # model not running, or an answer that cannot be read
                st.error(f"The model could not read this email: {e}\n\nTry again, or switch to 'Rules only'.")
                st.stop()
        result = qt.check(extraction, email)
        match_items(result.extraction.items, history)
        RAW.mkdir(parents=True, exist_ok=True)
        (RAW / f"{email.case_id}.txt").write_text(email.text, encoding="utf-8")  # raw layer of the data lake
        st.session_state.update(last_run=run_key, result=result, saved=saved)
else:
    st.stop()

result, saved = st.session_state["result"], st.session_state["saved"]
ex = result.extraction
if saved:
    st.caption("Using the saved answer for this email (data/lake/processed).")

# ---------- Verdict ----------
counts = {s: sum(i.severity == s for i in result.issues) for s in SEVERITY_ICONS}
if result.ready_to_quote:
    st.success("✅ **Ready to quote.** Nothing essential is missing. Look at the checks below before pricing.")
else:
    st.error(f"❌ **Not ready to quote.** {counts['blocking']} essential item(s) missing. "
             "A draft reply to the customer is below.")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Parts", len(ex.items))
c2.metric("🛑 Missing (blocking)", counts["blocking"])
c3.metric("⚠️ To check", counts["check"])
c4.metric("🔵 Assumptions", counts["assumption"])

# ---------- Quote card ----------
st.subheader("Inquiry")
columns = st.columns(3)
for n, (name, f) in enumerate(ex.header.items()):
    icon = report.ICONS[f.status].split()[0]
    columns[n % 3].markdown(f"{icon} **{label(name)}:** {report._show(f.value) or '—'}")

st.subheader("Parts")
match_fields = ("part_number", "description", "quantity", "unit", "pieces_per_unit", "material",
                "drawing_ref", "machine_model", "match_tier", "matched_part_number", "reference_price")
st.dataframe(report.items_table(ex, fields=match_fields).rename(columns=label), hide_index=True, width="stretch")
st.caption("✅ found in the email · ❌ missing · ⚠️ check · 🔵 our assumption")

# ---------- Issues ----------
st.subheader("What needs attention")
issues = report.issues_table(result)
if issues.empty:
    st.write("Nothing.")
else:
    issues["severity"] = issues["severity"].map(SEVERITY_ICONS)
    st.dataframe(issues.rename(columns=label), hide_index=True, width="stretch")

# ---------- Reply ----------
st.subheader("Draft reply to the customer")
if result.client_email:
    reply = st.text_area("Edit before sending", result.client_email, height=260)
    st.download_button("Download reply (.txt)", reply, file_name=f"reply_{email.case_id}.txt")
else:
    st.info("Nothing essential is missing, so there is no need to ask the customer.")

with st.expander("Evidence: where each value came from"):
    st.dataframe(report.evidence_table(ex).rename(columns=label), hide_index=True, width="stretch")
