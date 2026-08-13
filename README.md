# Enterprise Data Governance Agent

A multi-agent system that profiles a dataset, scores its quality, classifies and
masks personal data, ranks findings by risk, and routes the serious ones to a
human before anything is acted on.


[36e7c464-818e-4352-9e1a-d50d96ae8b81.webm](https://github.com/user-attachments/assets/efed8449-7587-44a5-8d3e-baf26484edb1)

## The one design rule

**Rules decide. The language model explains.**

Everything that produces a *number* — profiling statistics, quality scores, PII
matches, risk scores — is deterministic code in `governance/core/`. Everything
that produces a *sentence* — column descriptions, quality narratives, drafted
remediation — is the language model, in `governance/narrative/`.

The separation is structural, not a convention: `core/` imports pandas and numpy
and nothing else, so it cannot call a model even by accident. Model output is
only ever stored as text and is never parsed back into a value.

Consequence: the system produces a complete, correct governance report with the
model switched off entirely.

## Layout

```
governance/
├── config.py          every tunable value in the system, in one file
├── state.py           GovernanceContext + the objects inside it
├── synthetic.py       generates the evaluation dataset and its answer key
├── core/              deterministic. no model imports, ever.
├── policy/            regulation chunking + semantic retrieval
├── narrative/         language model layer, cache-first
├── graph/             LangGraph wiring
├── evaluate.py        precision / recall against the answer key
├── run.py             pipeline entry point
└── app.py             Streamlit dashboard
data/
├── synthetic/         evaluation set — defects planted by us, so measurable
└── demo/              real dataset — messy in ways we did not anticipate
policy/source/         official GDPR + CCPA text
out/                   governance_report.json · audit_log.jsonl · llm_cache.json
```

## Two datasets, two jobs

| | Evaluation set | Demonstration set |
|---|---|---|
| Data | synthetic, 500 rows × 14 cols | real, sampled |
| Answer key | 125 labelled defects | none — manual spot-check |
| Purpose | measure precision and recall | show it works on data we did not design |

You cannot measure a system without knowing the right answer in advance, and you
cannot claim it works in practice without running it on something you did not
build. Hence both.

## Setup

```bash
pip install -r requirements.txt
```

Then pick a model backend. **Either is optional** — the pipeline produces a
complete, scored, cited report with no model at all.

**Local (nothing leaves the machine):**

```bash
ollama pull qwen2.5:7b-instruct-q4_K_M
```

**Hosted, via Groq (much faster on a thin-and-light laptop):**

```bash
setx GROQ_API_KEY "your-key-here"
```

```bash
python -m governance.run --dataset synthetic --llm --backend groq
```

**Hosted, via xAI's Grok (a different provider from Groq above — check you
want this one and not the one above):**

Get a key at https://console.x.ai/, then:

```bash
setx XAI_API_KEY "your-key-here"
```

macOS/Linux, either backend — use `export` instead of `setx`:

```bash
export GROQ_API_KEY="your-key-here"
# or
export XAI_API_KEY="your-key-here"
```

```bash
python -m governance.run --dataset synthetic --llm --backend grok
```

Optionally override the model with `GROQ_MODEL` / `GROK_MODEL` env vars —
defaults are `llama-3.3-70b-versatile` (Groq) and `grok-4.5` (Grok); check
each provider's current model list before assuming a default stays accurate.

**Instead of exporting keys into your shell every time**, copy
`.env.example` to `.env` and fill it in — `python-dotenv` loads it
automatically (see `governance/narrative/client.py`), so `export`/`setx`
become optional. `.env` is git-ignored; never commit it.

Measured: a full cold run is ~2 minutes on a discrete GPU, an estimated 15–20
minutes on a 15 W ultraportable, and seconds via either hosted backend. Every
run is cached either way, so a second run is ~3.5 seconds regardless.

### Deploying to Streamlit Community Cloud

Streamlit Cloud does **not** read `.env` files, and its Secrets panel does
**not** become an OS environment variable — `os.environ.get("XAI_API_KEY")`
alone would find nothing there. `governance/narrative/client.py` checks
`st.secrets` first specifically to handle this; you don't need to change
any code, just configure the secret:

1. Push this repo to GitHub, then create the app on
   https://share.streamlit.io pointing at `governance/app.py`.
2. In the app's **Settings → Secrets**, paste (with real keys):
   ```toml
   GROQ_API_KEY = "your-groq-key-here"
   XAI_API_KEY = "your-xai-key-here"
   ```
   (`.streamlit/secrets.toml.example` in this repo has the same template —
   copy its contents rather than retyping them.)
3. Redeploy. `pdfplumber`, `fastembed`, `langgraph`, `streamlit` and
   `python-dotenv` all install from `requirements.txt` automatically; only
   `ollama` (the `auto` backend) won't work on Cloud, since there's no local
   Ollama server to reach there — use `groq` or `grok` as the backend when
   deployed.

For **local** development, either approach works: copy `.env.example` to
`.env`, or copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml`. If both exist, Streamlit secrets take priority
(see `_resolve_secret()` in `governance/narrative/client.py`).

### What leaves the machine

**No personal data reaches a prompt under any backend.** `describe.py`
withholds sample values for any column classified as personal data; every other
prompt carries only column names, statistics and findings.
`tests/test_privacy.py` asserts this against the real values in the dataset —
literal strings, not patterns that resemble them.

So the honest claim depends on the backend:

| Backend | Claim |
|---|---|
| `auto` (Ollama) | Nothing leaves the machine. |
| `groq` (Groq) | No **personal data** leaves the machine. Prompts do. |
| `grok` (xAI) | No **personal data** leaves the machine. Prompts do. |

The hosted ones are narrower and still a real control. Say the narrower one when
demonstrating with Groq.

## Usage

Generate the evaluation dataset and its answer key:

```bash
python -m governance.synthetic
```

Run the pipeline (no language model required):

```bash
python -m governance.run --dataset synthetic
```

Measure it against the answer key:

```bash
python -m governance.evaluate
```

Build the policy index (once, after dropping in the regulation text):

```bash
python -m governance.policy.build --query "customer email address"
```

Run through LangGraph instead (identical results — same node functions):

```bash
python -m governance.run --dataset synthetic --graph
```

Open the dashboard:

```bash
streamlit run governance/app.py
```

Run on any other CSV:

```bash
python -m governance.run --path data/demo/online_retail.csv
```

```bash
python -m pytest tests/ -q
```

## Orchestration

```
                 metadata
                 ╱        ╲       both consume the catalog, neither
           quality      compliance  consumes the other — so they fan out
                 ╲        ╱
                   join            barrier: both branches complete
                     │
       risk → cite → gate → recommend ⟶ narrative (conditional)
```

The graph does not reimplement the pipeline. Both it and the sequential runner
call the same functions in `governance/graph/nodes.py`, so parity is structural
rather than something that has to be re-verified. `tests/test_graph.py` asserts
it anyway, and also proves the claim that drives the state design: remove the
`operator.add` reducer from `issues` and LangGraph raises `InvalidUpdateError`
rather than guess how to merge two concurrent writes.

State carries two collections for that reason:

| key | role |
|---|---|
| `issues` | the **inbox** — quality and compliance both append; needs the reducer |
| `findings` | the **settled record** — written by risk scoring, then replaced as citation and gating apply |

They cannot share a key: an append reducer would double the list every time a
later node touched it.

## The dashboard

Five tabs, one per deliverable, plus the review queue. The dashboard is not a
sixth deliverable — it is the surface the other five are delivered through.

It reads `out/governance_report.json` and **never calls a model to render a
page**; all prose was generated and cached when the report was produced. A
dashboard that generates text on page load is one that stalls in front of an
audience.

The review queue holds every finding scoring `REVIEW_THRESHOLD` or above.
Approve and Reject stay disabled until a reviewer is named — a decision without
a named actor is not auditable. Decisions persist in
`out/review_decisions.json`, keyed on the finding id (a stable hash), so a
decision made today still attaches to the same finding after the next run.
Every decision is appended to `out/audit_log.jsonl`.

## The assistant

Scoped question-answering over the findings, not a general chatbot. Retrieval
runs over `governance_report.json` only — no access to the dataset, the
regulation corpus, or anything outside. Every answer names the finding ids it
drew on, and those ids come from the retrieval step rather than from the model,
so an answer cannot cite a finding that does not exist. Ask it something the
report cannot answer and it says so.

## The policy corpus

`policy/source/` holds the **verbatim official text** — GDPR Articles 4, 5, 6, 9,
25, 30, 32, 35 and Recital 26, plus CCPA §§1798.100, .105, .140 and .150. 105
passages in total. Refresh it with:

```bash
python -m governance.policy.fetch
```

Nothing is summarised on the way in. Chunks carry an `is_placeholder` flag that
propagates to every citation, and a test asserts the corpus is free of it.

**Queries are phrased in the regulation's vocabulary, not the database's.** This
is the single biggest factor in retrieval quality. Measured on this corpus:

| Query style | Top result | Score |
|---|---|---|
| `"a column named customer_email; the concern is unmasked pii column"` | CCPA breach liability ✗ | 0.405 |
| `"security of processing; encryption and pseudonymisation; appropriate technical measures"` | GDPR Art. 25, Art. 32 ✓ | 0.690 |

No regulation talks about columns, so searching with column names returns
whatever happens to be nearest. The mapping from finding to regulatory phrasing
lives in `config.RETRIEVAL_QUERY`. An issue type with no entry there is not
cited at all — a malformed email address is a quality defect, not a regulatory
matter, and attaching a statute to it would pad the report rather than inform it.

## Reading the evaluation

The synthetic set currently scores 1.000 precision and recall. **That is a
correctness check, not a performance claim.** We planted the defects and we
wrote the detectors, so anything less than a near-perfect score would mean the
plumbing is broken. What it demonstrates is that every detector is wired to the
right column and reports the right rows — nothing more.

Two things make the number meaningful, and both are outstanding:

- **Decoys** in the synthetic set — values that look like defects but are not,
  so precision has something to measure against.
- **The demonstration dataset**, where the defects were not chosen by us.

## Notes

`governance/synthetic.py` writes the answer key *as it plants each defect*, then
re-derives every defect from the finished file and refuses to write anything if
the two disagree. An answer key that silently contradicts its own dataset is
worse than none at all — every metric computed against it would be wrong, and
nothing about the output would look broken.
