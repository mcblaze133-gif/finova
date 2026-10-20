# Company evidence packs

Keep uploaded originals in the configured source folder, grouped as `<company-slug>/...`.
SignalAI writes derived material only in `SignalAI/company-packs/<company-slug>/`.

Use **Prepare / refresh evidence pack** on the home page. Excel export also checks
the pack before preparing inputs. For a local command, use:

```powershell
.\.venv\Scripts\python.exe -m tools.prepare_evidence_pack britannia
```

`manifest.json` points to the current version's combined PDF, visual HTML index,
searchable page text and financial-record provenance. Its source index records
each original filename, SHA-256 fingerprint and selected original PDF pages.
Original PDF page numbers include covers; they can differ from printed numbers.
Per-document folders hold screenshots and selected original pages. Versions are
preserved for audit; the source folder is never rewritten.

Selection keeps pages supporting reviewed financial records, neighboring context,
historical consolidated statements and tax/exceptional notes, fuller notes from
the latest annual report, and relevant pages from the two most recent calls and
presentations identified by reporting-period hints. Hints are unverified sort
keys, not publication dates. Whole pages are preserved; tables are not cropped.
Automatic selection can miss material information. Full originals remain the
fallback; none are deleted as irrelevant. Image-only PDFs need OCR/manual review.

The home page searches the selected pack first. Check **Search full originals**
to widen the search even when the shortlist has matches. With no shortlist match,
search falls back automatically. Replaced or missing source files are excluded
from current search until refreshed. Search snippets are evidence candidates,
not verified facts or AI conclusions.

Refreshing hashes source content, reuses stored text for unchanged documents,
and renders only changed page selections. Hashes also detect damaged generated
artifacts. All selected pages supporting the 83 Britannia reviewed financial
records were checked for inclusion. The shortlist is not independent financial
verification and does not add missing peer/market/capital-cost information.

Workbook exports use a separate input-and-code fingerprint. Repeating identical
inputs reuses an intact previously generated workbook. Assumption, data or model
changes invalidate it. A workbook with a changed file hash is preserved and a
fresh export is built; edits inside Excel are not automatically imported into
the central assumption records. Existing exports made before this feature are
not automatically trusted or enrolled in the reuse cache.

## Interfaces

* `GET /evidence/{company}`: published pack metadata.
* `POST /evidence/refresh`: body `{"company":"britannia"}`; returns HTTP 202
  with a refresh ID and status URL. It refreshes local evidence and checks online.
* `GET /evidence/refreshes/{id}`: progress and dated online review results.
* `GET /updates/{company}`: latest online refresh status and results.
* `GET /evidence/{company}/pdf`: selected original pages.
* `GET /evidence/{company}/search?q=palm%20oil&full=false`: shortlist/fallback search.

**Investigate** includes the latest online review and refreshes it when public
source refresh is requested for a company with a prepared local pack. Historical
cutoff runs exclude later online research. Excel exports include online review
notes, dated leads, source links, conditional impacts and review flags. They check
online if the previous refresh is older than 24 hours or its local baseline changed.
Actual financials and numerical assumptions remain separately reviewed inputs.

The local-only preparation command and local text search need no model calls.
The full website refresh queries five public Google News RSS searches without
a key. Headlines are leads, not verified events; article/event dates, direct company
exposure and quantitative effects still need checking. Unrelated company headlines
and routine price-action updates are filtered. Previously seen lead identifiers
are tracked; unseen leads are not proof of novel events.

When the confirmed free-tier key and local daily allowance permit, the configured
Gemini model interprets the actual retrieved feed headlines against diversified
local-pack excerpts. Exact headline quotes are required; events remain unverified,
confidence remains low and implications are conditional. Unsupported company
exposure is downgraded, unsourced dates removed and future occurrences rejected.
At most six relevant feed-based events are assessed per call.

The optional provider-search mode is disabled by default in
`config/online_research.json`: the Gemini 2.5 Flash-Lite search model documented
at https://ai.google.dev/gemini-api/docs/pricing returned HTTP 404 in the actual
free-key test on 18 October 2026. No paid replacement was selected. If an available
free search route is configured later, provider-supported spans and exact citations
are required; these still do not independently audit the original article.

The existing 25-call daily local guard covers search and review calls. A specifically
approved operator exception can grant at most two additional calls for one run on
one UTC day; it cannot extend that day's allowance again. Exhausted
allowance, missing grounding, quota failures and unavailable feeds produce a partial
report, never a claim that no news exists. There is no paid provider/model fallback.
Word duplicates are not generated. Peer normalisation, source verification,
company-specific numerical assumption revisions and desktop Excel checks remain
necessary before treating any valuation as current and fully reviewed.
