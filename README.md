# Finova

**Team 123 · Track C · Round 1 research prototype**

Finova investigates whether a company's reported progress is supported by its
operating economics. It connects company disclosures, financial statements,
management commentary, peer context and current public developments, then tests
competing explanations. Valuation is a cross-check, not proof of a discovery.

[Round 1 solution report](docs/123_TrackC_Round1.pdf) ·
[Reproduction requirements and limits](docs/REPRODUCIBILITY.md)

[Next-phase progress: incremental source refresh](docs/NEXT_PHASE.md)

[Statement intake and verification status](docs/STATEMENT_INTAKE.md)

## Demonstration

The working demonstration runs locally on Windows at `http://127.0.0.1:8000`.
Hindustan Unilever (HUL) is the prepared Round 1 case, covering FY2022–FY2026.
The reviewed local history has 83 of 85 statement values populated; this is not
a claim of complete financial or research coverage.

1. Select a company and click **Investigate company**.
2. The system reads its compact evidence pack, attempts a fresh bounded online
   update check, and runs planner, extractor, analyst and sceptical-review stages.
3. It builds a new research report and a matching editable Excel workbook from
   the run snapshot. Unchanged source extraction can be reused; prior model
   findings are not presented as a fresh investigation.
4. Read the PDF in the website and download the PDF and Excel outputs. Reports
   explain trends, investor relevance, scenarios, risks and evidence limits.

The private prepared company library is not shipped in this repository.
A fresh clone does not contain the demonstration's database or evidence packs.
No public deployment or demo-video URL is claimed by this README.

## Research and financial outputs

- Page-addressable PDF/CSV evidence, content hashes and source provenance.
- Hypotheses and alternatives with supporting and opposing searches.
- Evidence-linked calculations, timelines, counterarguments and falsification
  conditions. Missing independent corroboration remains visible.
- Detailed FMCG analysis with financial charts, current-development assessment
  and compact numbered source references.
- Separate visible Bear, Base and Bull Excel forecasts, editable assumptions,
  sensitivity analysis and method suitability checks. HUL currently has
  conditional FCFF DCF and DDM; its P/E and EV/EBITDA cases are unvalidated
  multiple stress tests. Other methods require suitable reviewed inputs.
- The exported workbook is an editable copy. Changing it does not automatically
  update an existing PDF or import edits back into the website.

News may flag demand, cost, regulatory or geopolitical exposure. An unverified
headline does not silently change forecast assumptions. A partial check remains
partial; neither a model answer nor multiple company documents count as
independent corroboration.

## Stack

Python 3.12, FastAPI, SQLite, Pydantic, HTTPX and pypdf; structured Gemini calls;
public RSS/search leads and permitted original-source retrieval; ReportLab PDF
reports; formula-driven Node.js Excel authoring. n8n JSON workflows are optional
backend adapters. The website calls FastAPI directly.

## Local setup (Windows / PowerShell)

The backend and offline fixtures can run from a clean clone. **Complete live
Excel/PDF generation additionally requires the separately provisioned
`@oai/artifact-tool` dependency. It is not distributed here and this repository
is not yet a standalone end-to-end installation.** See the reproduction document.

```powershell
git clone https://github.com/mcblaze133-gif/finova.git
cd finova
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/setup_local.py
.\start-backend.ps1
```

Open `http://127.0.0.1:8000`; API documentation is at `/docs`, health at `/health`.
Use one backend worker and keep the service bound to localhost. The initial
source library is empty; do not interpret the company list as populated data.

### Enable live research

1. Edit the generated, ignored `.env` locally and enter your own Gemini API key.
   Never commit it or paste it into issues.
2. Confirm the provider project has paid billing disabled before setting
   `GEMINI_FREE_TIER_CONFIRMED=true`. Provider model availability and quota apply.
3. Configure `config/library.json` with your local original-source folder.
   `config/company_folders.json` maps company IDs to direct child folders.
4. Follow [the source intake guide](inputs/SOURCE_LIBRARY_GUIDE.md) and
   [evidence-pack guide](inputs/EVIDENCE_PACK_GUIDE.md). Financial records require
   explicit units, periods, accounting scope and reviewed source evidence.

The normal local model ceiling is 100 attempts per UTC day, including failures;
it does not increase provider quota. There is no paid fallback. Keys, account
allowances and local billing confirmations are not transferred with this code.

### PDF / Excel runtime

Install reporting dependencies into the Python interpreter used for PDF builds:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-reporting.txt
```

`tools/setup_local.py` creates ignored `config/runtime.json` with `node` and
`pdf_python` paths. It preserves existing settings and credentials. Excel needs
Node.js with `@oai/artifact-tool` resolvable from this project. Report generation
currently uses Windows Arial fonts. Install Poppler's `pdftoppm` on PATH for
compact-pack screenshots and PDF-page rendering; the web reader also accepts
an explicit `pdftoppm` path in `config/runtime.json`. Fonts and third-party
binaries are not redistributed.

### Optional n8n

The exports in `workflows/` contain no credentials. Import them into your own
n8n installation and review localhost endpoints before enabling anything.
An existing installation can run with `npx.cmd n8n`; review npm's installation
prompt if n8n is not installed. `start-n8n.ps1` is for a preconfigured local
installation and requires your own ignored `config/n8n-runtime.json` paths.
The website does not need n8n to start.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Fixtures mock model responses and do not establish live provider availability,
financial correctness or successful reproduction of the full demonstration.
Some PDF/layout checks require the reporting dependencies. The engineering
checks do not certify a confirmed investment discovery.

For the real five-company website workflow, exact report-ID recovery and
PDF/Excel download checks, see [Cross-company checks](docs/CROSS_COMPANY_CHECKS.md).
Live checks consume the existing provider allowance. A pipeline pass and a
complete, independently corroborated research conclusion are different results.

## Repository map

| Folder | Purpose |
|---|---|
| `backend/` | Local API, evidence retrieval, research, valuation and report orchestration |
| `excel/` | Formula-driven workbook builder |
| `prompts/`, `schemas/` | Research roles and response contracts |
| `config/` | Public company configuration; machine-local settings excluded |
| `inputs/` | Source intake guides and blank CSV template |
| `workflows/` | Optional n8n workflow exports |
| `tests/` | Offline behavior and regression fixtures |
| `tools/` | Setup, evaluation, report builders and development utilities |
| `docs/` | Round 1 submission and reproduction status |

## Current limits and next steps

This is a local prototype with manually prepared financial cases. Broad,
company-independent coverage, autonomous financial intake, stronger independent
verification and held-out-company validation remain future work. PDF layout,
OCR/complex-table extraction, news access and model quotas can limit coverage.
Public source availability is not guaranteed. It makes no promise of error-free
investment conclusions.

Next steps through the finals: portable Excel authoring, narrower evidence
packs, faster independent retrieval, broader public-data coverage, more-company
validation, recovery/formula testing and clearer investor-facing website output.

The repository excludes API keys, `.venv`, original company PDFs, private data,
backups, logs, generated run outputs and machine-specific runtime settings.
Only deliberately selected demonstration artifacts belong in `docs/`.
No licence grant is implied by publishing the repository without a licence.
