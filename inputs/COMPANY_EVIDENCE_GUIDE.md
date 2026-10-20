# Reusable company evidence

Original PDF/CSV folders remain the source archive. Each populated company gets a
`SignalAI Evidence/index.html` entry point beside its originals. Open that file to
find selected original PDF pages, searchable text, page/file references, structured
page evidence and coverage warnings. Generated files are excluded from intake.

The workspace also keeps cached pages and screenshot previews in `company-packs/`.
Company folder aliases are recorded in `config/company_folders.json`.

Local preparation (no model/API calls):

    .venv/Scripts/python.exe -m tools.prepare_all_company_evidence

Publish the verified prepared copies into the user folders:

    .venv/Scripts/python.exe -m tools.prepare_all_company_evidence --publish

Publication requires source-folder write access, confirms that original files have
not changed, and retains prior generated versions. It never overwrites originals.
Unchanged artifacts are reused; modified source files or extracted text invalidate
the pack. If a document changes while preparing, refresh before publishing.

Selection is not verification of financial numbers. Historical statement pages,
available financial releases, detailed recent annual notes and recent call/deck
candidates are shortlisted automatically. Period hints are unverified sort keys,
not publication dates. Search the complete stored original text whenever the pack
does not answer a question. Complex tables, rotated text and scanned pages require
review against the original page; unavailable OCR is reported explicitly.

The financial-records file lists already reviewed records only. An empty file does
not mean there are no financial statements: it means the company has no reviewed
structured inputs yet. New PDF text and news headlines never become approved
valuation inputs automatically. CSVs must pass the existing financial intake schema
before they can contribute to valuations.
