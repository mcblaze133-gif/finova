# Reproduction status — Round 1

Finova is a local, single-user Windows research prototype. The demonstration
installation is more fully provisioned than a clean clone. This distinction matters.

| Component | Fresh-clone requirements / limits |
|---|---|
| Backend and offline tests | Python 3.12, `requirements.txt`, generated local settings. No API key required for offline tests. |
| Live research and news interpretation | A user-provided Gemini key, available provider quota, free-tier confirmation and suitable public/local evidence. Retrieval can be incomplete. |
| Company evidence | Supply original PDF/CSV files and review normalized financial records. The private database, company originals and generated evidence packs are excluded. Company configuration is not a populated financial database. |
| Excel generation | Node.js and the separately provisioned `@oai/artifact-tool` package, imported by `excel/build.mjs`. This package came from the development environment; this repository does not distribute it or claim it is publicly installable. End-to-end Excel/PDF generation is not independently reproducible from this clone alone without that dependency. |
| PDF generation | Reporting dependencies, Windows Arial fonts and a successfully generated workbook snapshot. |
| Evidence screenshots / web PDF reader | Poppler (`pdftoppm`) on PATH or configured as described in the README. |
| n8n | Optional workflow adapters; not required for the website. Import JSON exports into your own n8n installation. Never import someone else's credential database. |

The full Excel authoring dependency must be made portable or replaced with a
redistributable implementation before claiming one-command end-to-end setup.
That replacement has not been completed in Round 1.

Offline fixture tests establish specified software behavior, not financial
accuracy, a corroborated investment discovery, exhaustive news coverage or
successful live generation on another machine. Valuations remain conditional
on evidence, applicability and analyst assumptions.

No sample API keys, live databases, internal logs or original company PDFs are
published. Historical scripts may contain development-machine paths; these do
not configure a new installation. Use `tools/setup_local.py` for machine-local
runtime and library settings.
