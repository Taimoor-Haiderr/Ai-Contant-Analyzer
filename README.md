# AI Content Analyzer & Natural Rewriter

A local Python engine that:

1. **Analyzes** text and documents for linguistic/statistical patterns that are
   *commonly associated with* AI-generated writing, and
2. **Rewrites** content into clearer, more natural language while preserving
   meaning, facts, names, numbers, dates, citations and structure, and
3. **Explains every change it made** in a transparent change report.

Two ways to use it: a premium web dashboard (`python server.py`) or a CLI
(`python app.py`). All logic lives behind one Python API (`api.py`); the web
layer and the CLI are both thin callers of it.

---

## 1. What this project does (and does not) claim

This tool reports **indicators, not proof**.

- It never outputs an accuracy percentage, because no representative benchmark
  has been run against it.
- It uses labels instead: **Low indication / Moderate indication /
  High indication / Inconclusive**, plus a separate confidence label.
- Samples under ~80 words are forced to `Inconclusive`.
- It makes **no claim** that rewritten content will bypass any external AI
  detector. That is not the goal; readable, honest writing is.
- Human writing is frequently flagged as AI-like, and model output is
  frequently missed. Treat every result as a discussion starter.

---

## 2. Python version

**Python 3.10 or newer** (tested on 3.12). The code uses modern type-union
syntax (`str | None`), so 3.9 and below will not run it.

---

## 3. Installation

```bash
# 1. get into the project
cd AI-Content-Analyzer

# 2. create a virtual environment
python -m venv .venv

# 3. activate it
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate

# 4. install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Dependencies

| Package        | Why it is needed                                   |
|----------------|----------------------------------------------------|
| python-dotenv  | loads `.env` configuration                         |
| requests       | HTTP calls to the model provider                   |
| PyMuPDF        | PDF reading + simple PDF writing                   |
| python-docx    | `.docx` reading and writing                        |
| pandas         | CSV handling                                       |
| openpyxl       | `.xlsx` reading and writing                        |

Nothing else is installed. No database, no web framework, no auth library.

---

## 4. `.env` configuration — you must create this yourself

The repository ships **`.env.example` only**. Your real `.env` is git-ignored
and must never be committed.

```bash
# macOS / Linux
cp .env.example .env
# Windows
copy .env.example .env
```

Then open `.env` and fill in your own values:

```ini
MODEL_PROVIDER=openai          # openai | anthropic | mock
MODEL_API_KEY=your_api_key_here
MODEL_NAME=your_model_name
MODEL_BASE_URL=optional_model_endpoint

TEST_MODE=true                 # true = offline mock, no key required
MODEL_TEMPERATURE=0.3
MAX_CHUNK_CHARS=6000
REQUEST_TIMEOUT=120
MAX_RETRIES=2
```

**Key handling rules enforced in code:**

- Keys are never hard-coded in any `.py` file.
- Keys are never printed. `Settings.describe()` shows a masked hint only
  (`sk-...45 (51 chars)`).
- Every outbound error message is passed through `sanitize()`, which strips the
  key out of provider responses before it can reach a log or the user.

### Provider examples

| Provider    | `MODEL_PROVIDER` | `MODEL_BASE_URL`                      | `MODEL_NAME` example        |
|-------------|------------------|---------------------------------------|-----------------------------|
| OpenAI      | `openai`         | *(leave blank)*                       | `gpt-4o-mini`               |
| OpenRouter  | `openai`         | `https://openrouter.ai/api/v1`        | `openai/gpt-4o-mini`        |
| Groq        | `openai`         | `https://api.groq.com/openai/v1`      | `llama-3.3-70b-versatile`   |
| Ollama      | `openai`         | `http://localhost:11434/v1`           | `llama3.1`                  |
| Anthropic   | `anthropic`      | *(leave blank)*                       | `claude-sonnet-4-5`         |

Because everything goes through `core/ai_provider.py`, swapping providers is a
`.env` edit — no application code changes.

---

## 5. How to run

```bash
python server.py        # web dashboard at http://127.0.0.1:5000
python app.py           # or the CLI
```

The CLI menu:

```
   1. Analyze text            7. Analyze CSV
   2. Rewrite text            8. Rewrite CSV
   3. Analyze PDF             9. Analyze XLSX
   4. Rewrite PDF            10. Rewrite XLSX
   5. Analyze DOCX           11. Generate report from last result
   6. Rewrite DOCX           12. Exit
   c. Show configuration      s. Create sample test files
```

For text input (options 1 and 2), paste your content and finish with a line
containing only `END`.

For file options, drop your file into `input/` and type just the file name.

---

## 6. Supported file types

| Type              | Extract                                  | Rewrite output                            |
|-------------------|------------------------------------------|-------------------------------------------|
| Plain text        | `.txt`, `.md`                            | new `.txt`                                |
| PDF               | `.pdf` (block-based paragraph recovery)  | new text-only `.pdf`                      |
| Word              | `.docx` (headings, paragraphs, tables)   | new `.docx` (copy, styles preserved)      |
| CSV               | `.csv` (text columns only)               | new `.csv`                                |
| Excel             | `.xlsx`, `.xlsm` (text cells only)       | new `.xlsx` (formulas preserved)          |

Old `.doc` and `.xls` are **not** supported — save as `.docx` / `.xlsx` first.

---

## 7. Example workflow

```
INPUT
  ↓  processors/*.extract()
CONTENT EXTRACTION
  ↓  processors.normalize_text()
CONTENT NORMALIZATION
  ↓  core/chunker.chunk_text()   (order-preserving, lossless)
AI CONTENT ANALYSIS              core/analyzer.analyze_content()
  ↓
DETAILED ANALYSIS REPORT         reports/report_generator.build_report()
  ↓
NATURAL REWRITE                  core/rewriter.rewrite_content()
  ↓
CHANGE ANALYSIS                  core/change_report.build_change_report()
  ↓
BEFORE / AFTER RESULT            core/change_report.build_before_after()
  ↓
EXPORT                           exports/exporter.py
```

Programmatic use:

```python
import api

result = api.rewrite_docx("input/assignment.docx")

if result["ok"]:
    print(result["analysis"]["ai_likelihood"])          # "Moderate indication"
    print(result["changes"]["summary"]["total_changes"])
    print(result["output_file"])                        # new .docx, original untouched
    api.export_result(result, formats=("txt", "json", "html", "pdf"))
else:
    print(result["error"]["code"], result["error"]["message"])
```

Nothing raises on expected failures. Every API function returns either
`{"ok": True, ...}` or `{"ok": False, "error": {"code", "message", "detail"}}`.

---

## 8. Output locations

| What                       | Where                       |
|----------------------------|-----------------------------|
| Your input files           | `input/`                    |
| Rewritten documents        | `output/`                   |
| JSON / TXT / HTML / PDF reports | `output/reports/`      |

**Originals are never modified.** DOCX and XLSX rewrites copy the file first,
then edit the copy. Output names never overwrite: if
`sample_natural_rewrite.docx` exists, the next run writes
`sample_natural_rewrite_2.docx`.

> Note on `.gitignore`: the spec listed `reports/` as ignored, but `reports/` is
> also a Python package (`reports/report_generator.py`). So generated reports go
> to `output/reports/`, and `.gitignore` ignores `output/` plus
> `reports/*.json|txt|html|pdf` — never the source file.

---

## 9. Test mode (no API key needed)

Set `TEST_MODE=true` in `.env` and the whole pipeline runs against
`MockProvider` — a local, rule-based stand-in that contacts no network.

Use it to verify: text extraction, PDF extraction, DOCX extraction, CSV
reading, XLSX reading, chunking, report generation, exporting, and the
"original file untouched" guarantee.

Every mock result is stamped `"mode": "mock"` and every report says so in plain
English, so mock output can never be mistaken for real model analysis. The mock
rewrite only simplifies a fixed list of wordy phrases; **real contextual
rewriting requires a connected model.**

---

## 10. How to test each file type

```bash
# 1. create sample files for every supported format
python make_samples.py
#    -> input/sample.txt, sample.pdf, sample.docx, sample.csv, sample.xlsx

# 2. make sure TEST_MODE=true in .env, then:
python app.py
```

Then walk the menu:

| Option | File               | What to check                                              |
|--------|--------------------|------------------------------------------------------------|
| 1 / 2  | pasted text        | statistics, indicators, change list                        |
| 3 / 4  | `input/sample.pdf` | paragraph count > 1; new PDF in `output/`                   |
| 5 / 6  | `input/sample.docx`| heading style and table survive in the output `.docx`       |
| 7 / 8  | `input/sample.csv` | `id`, `rating`, `signup_date` untouched; `feedback` rewritten |
| 9 / 10 | `input/sample.xlsx`| both sheets kept; `=C2*2` and `=SUM(...)` still formulas    |
| 11     | —                  | writes JSON + TXT + HTML + PDF reports                      |
| c      | —                  | shows config with the key **masked**                        |

Quick non-interactive check:

```bash
python -c "import api; r=api.analyze_file('input/sample.docx'); print(r['ok'], r['analysis']['ai_likelihood'])"
```

Error handling can be exercised deliberately:

```bash
python -c "import api; print(api.analyze_file('input/nope.txt')['error']['code'])"   # file_not_found
python -c "import api; print(api.analyze_text('  ')['error']['code'])"               # empty_content
```

---

## 11. Known limitations

- **Rewritten PDFs are text-only.** Layout, images, columns and fonts from the
  source PDF are not reproduced. Faithful PDF layout cloning is out of scope.
- **Scanned PDFs are rejected, not OCR'd.** You get a clear
  `scanned_document` error telling you to run OCR first (e.g. OCRmyPDF).
- **DOCX in-place rewriting requires matching paragraph counts.** If the model
  merges or splits paragraphs, the engine builds a clean new document instead
  of risking text landing in the wrong paragraph, and says so in the warnings.
- **Tabular rewriting costs one small request per distinct text cell.** This is
  deliberate: batching cells risks misalignment between rows. Duplicate cell
  values are cached. A warning appears above 150 distinct cells.
- **Cell detection is heuristic.** A cell is rewritten only if it has 4+ words
  and does not look numeric, like a date, a URL, an email or an ID. Short
  labels and codes are left alone, which occasionally means genuine prose in a
  3-word cell is skipped.
- **The sentence splitter is regex-based.** Abbreviations like "Dr." or "e.g."
  can inflate the sentence count slightly.
- **Readability is Flesch reading ease with a heuristic syllable counter** —
  directionally useful, not clinically exact.
- **Passage-level flagging depends on the model** quoting the source exactly.
  Passages are never edited during analysis, but a paraphrasing model may
  return a near-quote.
- **No database, no accounts, no persistence.** Each run is independent.

---

## 12. AI-detection limitations (read this)

No method can reliably determine whether a human or a model wrote a text —
including this one.

- Formal, technical, non-native-English and heavily-edited human writing often
  trips the same indicators as model output.
- A model told to write casually often trips none of them.
- Indicators compound — several moderate signals are more meaningful than one
  strong one, but still not proof.
- **Do not use this tool to accuse anyone of anything.** Use it to understand
  why a piece of writing reads the way it does.

Every report ends with this disclaimer automatically (`config.DISCLAIMER`).

---

## 13. Phase 2 — the dashboard

The frontend is built. `server.py` is a thin HTTP wrapper around `api.py` and
adds **no processing logic**; `frontend/` is plain HTML, CSS and vanilla
JavaScript with no framework and no build step.

### Run it

```bash
pip install -r requirements.txt     # now also installs Flask
python server.py
# open http://127.0.0.1:5000
```

The CLI (`python app.py`) still works exactly as before — the engine does not
depend on Flask.

### Routes

| Method | Route                    | Calls                    |
|--------|--------------------------|--------------------------|
| GET    | `/api/health`            | safe config summary      |
| POST   | `/api/analyze/text`      | `api.analyze_text`       |
| POST   | `/api/rewrite/text`      | `api.rewrite_text`       |
| POST   | `/api/upload`            | saves to `input/uploads/`|
| POST   | `/api/analyze/file`      | `api.analyze_file`       |
| POST   | `/api/rewrite/file`      | `api.rewrite_file`       |
| POST   | `/api/export/<job_id>`   | `api.export_result`      |
| GET    | `/api/download/<token>`  | streams a generated file |
| POST   | `/api/session/clear`     | forgets in-memory results|

Results live in two process-memory dictionaries. No database, no accounts, no
persistence. Restarting the server clears the session, and the UI says so.

### Pages

Dashboard · Text Analyzer · Documents · Natural Rewrite · Reports · History ·
Settings. The flow the UI is built around:

```
paste or upload -> analyze -> read the report -> natural rewrite
                -> see exactly what changed -> download
```

### Front-end files

```
frontend/
├── index.html
├── css/  style.css · dashboard.css · analyzer.css · responsive.css
└── js/   api.js · ui.js · app.js · dashboard.js · analyzer.js
         uploader.js · rewriter.js · reports.js · downloads.js
```

`js/api.js` holds the single `API_BASE_URL` constant. Leave it empty to talk to
the same origin, or set `window.API_BASE_URL` before the scripts load to point
the dashboard at a different host.

### Design system

White background, brown accents, cream gradients. Tokens live at the top of
`css/style.css` (`--brown: #6B4423`, `--cream: #F3EDE6`, and so on) — change
them there and the whole dashboard follows.

### What the UI will not do

- No accuracy percentage and no "AI detector bypass" claim. The gauge shows the
  engine's label and repeats the limitation text next to it.
- No fabricated numbers. Every stat, change count and indicator comes from a
  backend response; when there is no data the page shows an empty state.
- No API key in the browser. `/api/health` returns only a boolean saying whether
  a key is configured.
- Upload errors quote the name you uploaded, never an internal path.

## 14. Project structure

```
AI-Content-Analyzer/
├── app.py                      # temporary Phase 1 CLI
├── api.py                      # public API — the frontend seam
├── config.py                   # .env settings, paths, shared disclaimer
├── make_samples.py             # generates test files for every format
├── requirements.txt
├── .env.example                # copy to .env and fill in
├── .gitignore
├── README.md
│
├── core/
│   ├── ai_provider.py          # OpenAI-compatible / Anthropic / offline mock
│   ├── analyzer.py             # statistics + chunked analysis + merging
│   ├── rewriter.py             # chunked rewrite + preservation verification
│   ├── change_report.py        # transparent change reporting
│   ├── chunker.py              # lossless, order-preserving chunking
│   ├── validator.py            # JSON extraction, repair, schema coercion
│   ├── prompts.py              # prompt templates
│   └── errors.py               # typed error hierarchy
│
├── processors/
│   ├── __init__.py             # ExtractedDocument, path safety, normalization
│   ├── text_processor.py
│   ├── pdf_processor.py
│   ├── docx_processor.py
│   ├── csv_processor.py
│   └── xlsx_processor.py
│
├── reports/
│   └── report_generator.py     # JSON / TXT / HTML / PDF rendering
│
├── exports/
│   └── exporter.py             # every download/export function
│
├── server.py                   # Phase 2: thin HTTP wrapper around api.py
├── frontend/                   # Phase 2: HTML + CSS + vanilla JS dashboard
│   ├── index.html
│   ├── css/  style.css, dashboard.css, analyzer.css, responsive.css
│   └── js/   api.js, ui.js, app.js, dashboard.js, analyzer.js,
│             uploader.js, rewriter.js, reports.js, downloads.js
│
├── input/                      # put your files here (uploads land in input/uploads/)
└── output/                     # results; output/reports/ for reports
```

