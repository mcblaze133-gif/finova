# Next phase: incremental source refresh

Implemented on 22 October 2026, after the preserved `round1` snapshot.

## Working change

Every original-source check still makes a network request and enforces the
existing public-host, domain, redirect, robots, size and request limits.
When a server provides ETag or Last-Modified validators, subsequent checks send
conditional headers. A real HTTP 304 can reuse a hash-checked body. A failed,
blocked or timed-out request never silently returns the old content.

PDF/HTML extraction is cached separately by source bytes, content type, parser
code, parser version and limits. Unchanged input can reuse the same extracted
pages. Changed or corrupted content requires parsing again. This cache does
not replace dated news checks, model interpretation or company-specific review.
It does not promote extracted text into verified financial facts.

Private cache files live beside the selected database under `source-cache/`.
They are derived working files, not a replacement for authoritative originals.
The application's excluded `data/` folder keeps the normal cache out of GitHub.
Receipt metadata records when a source was checked and whether its body was
revalidated by HTTP 304; these are access records, not publication dates.

## Checks

- 191 offline regression tests passed in a separate environment with reporting
  dependencies installed. No skipped tests in that environment.
- Nine new tests cover changed/unchanged sources, HTTP failures, corrupt
  bodies and parsed text, robots/private-host restrictions, size limits,
  no-store responses and malformed validator headers.
- Two live checks of HUL's results PDF returned identical bytes and 47 PDF
  pages. Parsing measured 12.180 seconds initially and 0.035 seconds subsequently.
  The server returned HTTP 200 both times; no live download saving is claimed.
  Source fetches measured 4.941 and 5.856 seconds. This is a single-source
  measurement, not an end-to-end investigation benchmark or latency guarantee.
- The PDF parser warned about rotated text. Cached output preserves the same
  extraction; it does not resolve OCR/layout gaps or establish completeness.
- No Gemini requests or financial-fact imports were used for these checks.

## Remaining work

The first candidate-intake implementation and visible verification register are
now documented in [Statement intake](STATEMENT_INTAKE.md). Promotion still needs
review, and full automatic normalization remains incomplete.

1. Automatically discover and reconcile new financial-statement inputs with
   explicit period, unit, scope, restatement and source review checks.
2. Make the Excel authoring runtime independently installable or replace its
   separately provisioned dependency without losing live formulas/features.
3. Validate stronger independent evidence and hypothesis rejection across
   held-out companies; measure complete investigation latency.
4. Bound total cache disk usage and manage retained versions for larger corpora.

This change improves repeated source work. It does not make the full research
and valuation system autonomous.
