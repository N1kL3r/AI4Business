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
| `notebooks/01_extraction.ipynb` | Step-by-step demo: emails → extraction → checkpoint → score |
| `data/` | Sample emails, answer keys and the data lake. **Not in git** (company data, see below) |

## Setup

```bash
pip install -r requirements.txt
```

For the LLM part, install [Ollama](https://ollama.com) and pull a model (runs locally, free, no data leaves the laptop):

```bash
ollama pull qwen2.5:7b
```

Then open `notebooks/01_extraction.ipynb`. Without Ollama the notebook still runs on the rule-based baseline.
Tests: `python -m pytest tests`.

## Data

The sample emails and answer keys come from the testbed firm under the project's data agreement and are
kept out of this public repository. Place them in `data/inbox/*.txt` (one email per file: header lines,
a blank line, then the body) and `data/test_cases/*.json` (same file name, the expected values; `null` = not in the email).
