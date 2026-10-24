# Cross-company demonstration checks

## 24 October 2026 results

Fresh investigations and downloaded artifacts passed the workflow checks for
all five prepared companies. All five delivered PDF readers, report-bound
verification registers and new editable workbooks passed identity checks.
Tata Consumer was investigated again after a model timeout left most operating
sections missing in its first report. The new report replaced it in the
readiness selection; the earlier report remains recorded.

| Company | Historical periods | Reviewed source records with matching file hashes | Operating areas complete | Measured run time |
|---|---:|---:|---:|---:|
| Britannia | 5 | 83/83 | 9/9 | 4m 05s |
| HUL | 5 | 87/87 | 8/9 | 5m 40s |
| ITC | 5 | 72/72 | 9/9 | 4m 44s |
| Nestle India | 4 | 60/60 | 8/9 | 4m 22s |
| Tata Consumer | 5 | 86/86 | 9/9 | 2m 59s |

These are individual observed durations, not latency guarantees. All five
reports remain qualified: news-source verification and corroborated discoveries
are incomplete. HUL and Nestle's competition/moat assessments remain partial.
The source-record counts describe recorded reviews and file integrity, not an
independent issuer-authenticity check. The same shared pipeline was used with
each company's reviewed inputs and explicit analyst assumptions.

The reporting-enabled offline suite passed 212 tests without skips. Independent
workbook checks passed for the exact five selected exports, including 370
historical cells matched to reviewed inputs. PDF layout checks rendered every
page and found no horizontal text overflow or chart connections across
incompatible historical periods. The test session used 42 of the existing
100 daily model attempts, including the initial Tata Consumer run.

The subsequent backend audit passed all 50 checks after starting the installed
local n8n service. Its seven imported workflow definitions match the project
exports and remain inactive. These checks do not claim that n8n orchestrated
the website investigations; the website's research pipeline runs in the backend.

The current local demonstration covers the five populated source folders:
Britannia, Hindustan Unilever, ITC, Nestle India and Tata Consumer. Folder
presence is not proof of current index membership. Empty folders do not count
as supported financial coverage.

## Run the real workflow

With the backend running locally, run from the project root:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_fresh_company_reports
```

This consumes real provider attempts under the existing daily cap and free-tier
settings. It starts a new report for each company, sequentially. It does not
change provider allowances, use a paid fallback, or select an earlier saved
report as the result of a new investigation. The audit filename is printed at
startup and stays in the private, Git-excluded `reports/` directory.

If a connection is interrupted, resume the exact printed audit file:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_fresh_company_reports --resume reports/<printed-audit-name>.json --retry-failed
```

Successful entries are retained. An existing job is polled using its exact ID;
a failed status read never triggers another job-creating request. Persistent
connection failures stop the audit before another company can collide with
the still-running job. A terminal failed investigation is retained as failed;
use a new explicitly selected company run to investigate again.

## What a pipeline pass establishes

- A new company-matched report and a new update-check ID were created after
  this audit requested them.
- Selected physical compact-PDF pages were re-read. This is question-directed
  evidence retrieval, not an assertion that every original PDF page was read.
- The PDF download matches its saved bytes, and the Excel download matches
  the workbook hash bound into the report.
- Excel findings link to this exact report. All three live scenario builds,
  historical statements and source register exist. No saved formula errors
  are accepted by the workbook reader.
- The website's verification register matches the frozen report register.
- Scope, coverage gaps, news-check status and source-review counts are retained
  separately from the pass/fail result.

Run the additional independent calculation and period checks after the jobs
finish:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_completed_models
.\.venv\Scripts\python.exe -m tools.verify_statement_workbooks
```

The first checks FCFF, EBIT, equity bridges, weights and ITC's segment roll-up.
The second checks delivered historical cells against reviewed inputs, units,
missing-value handling and period/scope comparability. These two read the
latest exports; use the live audit's exact IDs to confirm they tested the
same newly generated outputs.

## What a pass does not establish

A pipeline pass is not a complete research verdict, an authenticity certificate
or investment approval. Company documents can support analysis without providing
independent corroboration. News headlines can be current leads without being
verified events. File hashes establish consistency with saved files, not issuer
authenticity. Recorded source review is not a new numerical re-audit on every
request.

Financial statements, market observations and assumptions retain their own
dates. A fresh investigation does not turn a dated market reference into a live
quote. Analyst assumptions stay labelled estimates. Peer-backed comparable
analysis and transaction valuation require their own reviewed datasets; multiple
stress tests do not replace those datasets. Native desktop Excel recalculation
remains a separate unverified check.

HUL and ITC retain reporting-scope breaks; Nestle's 15-month period must not be
treated as an ordinary twelve-month growth comparison. The same pipeline runs
across the companies, using company-specific reviewed inputs and assumptions.
It does not claim fully autonomous financial-input review or method selection.

## Unavailable discovery service

A connection failure to the independent discovery service starts a 60-second
backoff for that service. Requests during that interval retain a coverage gap;
they do not receive earlier articles. After expiry, a new request is attempted.
Company-news feeds and official-source retrieval remain separate. This bounds
repeated waits on one unreachable service without marking research complete.
Restart the local backend after a code update to load this behavior.

Structured model calls can retry a transport failure once using the same
configured provider and model. Both attempts consume the application allowance;
authentication/quota errors and invalid structured responses are not retried.
Section calls use a 50-second request timeout to leave room for that retry
inside their existing 120-second outer budget. Persistent failures remain
visible and do not substitute old analysis.
