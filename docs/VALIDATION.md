# Publication checks — 20 October 2026

Checked a separate code-only snapshot using a new Python 3.12 virtual
environment, installed core and reporting requirements, and generated local
settings with blank credentials. No private database, company originals,
prepared packs, API key or previous outputs were copied into that snapshot.

- Offline suite: 182 tests, all passed, no skipped tests.
- Dependency consistency: `pip check` passed.
- API/website startup with a new local database: `/health`, `/`, `/companies`
  and `/docs` returned HTTP 200 through the application's ASGI interface and
  startup/shutdown lifespan. This was not an external-browser live research run.
- Staged publication scan: 153 files checked; no excluded private files,
  matches to configured local secrets or recognized credential patterns found.
  Automated scanning cannot establish that every possible secret format is absent.
- No live model requests used for publication checks.

The fresh-copy test found and corrected schema initialization during local
setup and removed a test's dependence on the private Britannia registry.

These checks do not establish a complete end-to-end research/Excel/PDF run
from a clean clone: the separately provisioned Excel authoring package and
company evidence are still required. See [reproduction status](REPRODUCIBILITY.md).
