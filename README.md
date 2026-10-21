# AI4Business: Group 14 quote assistant

Turns customer inquiry emails (requests for quotation) into checked quote drafts for a made-to-drawing
bronze parts manufacturer. The tool reads the email, fills in a quote template, reports what is
**missing** instead of guessing, and drafts a reply asking the client for anything that blocks the quote.

## Structure

| Path | What it is |
|---|---|
| `quotetool/schema.py` | The quote template. Every field has a status: found, missing, inferred, needs_review |
| `quotetool/extract.py` | The LLM reads the email and fills in the template |
| `quotetool/baseline.py` | Rule-based extractor (no AI) for comparison |
| `quotetool/checks.py` | Plain-code checks: is the evidence really in the email, YC default terms, what blocks the quote |
| `quotetool/evaluate.py` | Scores an extraction against a hand-made answer key |
| `quotetool/llm.py` | One function to call the model: local Ollama, or any OpenAI-compatible API |
| `app.py` | The web app for sales: drop in an email, get the quote card, what is missing, and a draft reply |
| `notebooks/01_extraction.ipynb` | Evaluation: emails → extraction → checkpoint → score, AI models vs. rules |
| `data/` | Sample emails, answer keys and the data lake. **Not in git** (company data, see below) |

## Setup

```bash
pip install -r requirements.txt
```

For the LLM part, install [Ollama](https://ollama.com) and pull a model (runs locally, free, no data leaves the laptop):

```bash
ollama pull qwen3.5:9b      # or qwen3.5:4b on a laptop with 8 GB RAM
```

Start the app (opens in your browser at http://localhost:8501):

```bash
streamlit run app.py
```

For the evaluation, open `notebooks/01_extraction.ipynb`. Without Ollama the notebook still runs on the rule-based baseline.
Tests: `python -m pytest tests`.

## Data

The sample emails and answer keys come from the testbed firm under the project's data agreement and are
kept out of this public repository. Place them in `data/inbox/*.txt` (one email per file: header lines,
a blank line, then the body) and `data/test_cases/*.json` (same file name, the expected values; `null` = not in the email).

## Running the app for others

The app runs where Ollama runs, and the emails never leave that computer.

- **Demo / single user:** `streamlit run app.py` on a laptop with Ollama.
- **Sales team in the office:** run it on one office PC or server with Ollama (enough RAM, ideally a GPU), started with
  `streamlit run app.py --server.address 0.0.0.0`. Colleagues open `http://<that-computer's-IP>:8501` on the company network.
  Do not expose it to the internet: there is no login.
- **Not suitable:** Streamlit Community Cloud or other public hosting. They cannot run Ollama, so emails would have to go to
  an outside AI service, and the data would leave the company.
