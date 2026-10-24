# Statement intake and verification register

Implemented 24 October 2026. No model calls are required to scan cached PDF text.

## What happens automatically

Refreshing a compact evidence pack now scans the uploaded, archived original
PDFs for a supported annual statement layout. New candidates retain the company,
document hash, physical source page, exact source row, metric, amount, scale,
accounting basis and reporting dates. Unchanged documents skip repeat parsing.

The first parser supports two-column annual primary statements with explicit
headings and ordered annual dates. It proposes revenue, D&A, finance costs,
total assets/liabilities and explicitly labelled operating cash flow when
supported. It does not infer parent PAT from group profit, EBITDA from a label
with different economics, missing capex, or a zero from a blank/dash.

This is a narrow candidate-intake implementation, not complete automatic
financial normalization. Unsupported tables, rotated/scanned pages, ambiguous
currencies, restated numbers and nonstandard reporting periods need further work.

## Review before valuation use

Candidates remain outside the valuation library until an explicit review:

- Rechecks the current source file hash and the quoted source row.
- Confirms currency, operating scope, publication date and annual column/period
  mapping. Proposed twelve-month starts are labelled as inferred until reviewed.
- Rejects future periods or publication dates preceding the period end.
- Checks conflicts with existing reviewed records on a normalized INR basis.
- Records a review explanation and time, with `user_verified` attribution.

Approval adds a source-linked record. It never overwrites an existing reviewed
input. A restatement conflict requires reconciliation. Source changes and parser
changes prevent old pending candidates from being silently approved. Reviews
are idempotent and preserve the audit trail.

## Verification is visible

New PDFs include a compact Appendix C table describing checks for historical
inputs, source authenticity, current developments, assumptions, Excel/report
binding and research conclusions. Website results show the same report-bound
summary and link to its source-by-source verification register. A fresh audit is
dated separately from the original research/news check.

File integrity, recorded source review and source attribution are distinct from
independent confirmation of issuer authenticity or a financial conclusion.
Inputs with missing hashes/review explanations show incomplete checks. Analyst
assumptions remain estimates. Native desktop Excel recalculation remains
unverified. A partial news check remains partial.

## Local operations

Restart the backend to load new routes and run its idempotent schema migration.
The scanner can also be run without an investigation:

```powershell
.\.venv\Scripts\python.exe -m tools.scan_statements hul
```

| Route | Purpose |
|---|---|
| `POST /statement-intake/scan` | Scan the registered company's imported originals |
| `GET /statement-intake/{company}` | Review source-linked candidates and their status |
| `POST /statement-intake/candidates/{id}/review` | Explicitly approve/reject with explanation and confirmations |
| `GET /verification/{company}` | Current library review/integrity status |
| `GET /analysis-reports/{id}/verification` | Report-bound verification register attached to that report version |

Request schemas and review fields are available in local `/docs`.
The approval workflow is intended for the local analyst. It has not been
exercised against production HUL data; the production scan has approved nothing.

## HUL check

The initial HUL scan covered 62 local document mappings and produced 22 pending
candidates. A repeat scan skipped all 62 mappings and added no candidates.
No reviewed financial records, assumptions, valuation values or model allowances
were changed. The latest HUL PDF was supplemented with an audit covering 87
source-input records, including the historical statement references. This is a
count of records, not 87 distinct financial measures or proof of full coverage.

The eleven new fixture tests cover unsupported layouts, duplicate rows, ambiguous
currency, stale originals, explicit review, conflicts, idempotency and honest
verification statuses. The full clean-environment suite passed 202 tests.
