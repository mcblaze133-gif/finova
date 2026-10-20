CREATE TABLE IF NOT EXISTS companies (
 id TEXT PRIMARY KEY, legal_name TEXT NOT NULL, business_model TEXT NOT NULL,
 profile_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_sources (
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
 url TEXT NOT NULL, source_family TEXT NOT NULL, retrieved_at TEXT NOT NULL,
 UNIQUE(document_id,url)
);
CREATE TABLE IF NOT EXISTS research_runs (
 id TEXT PRIMARY KEY, company TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, evidence_cutoff TEXT NOT NULL, status TEXT NOT NULL,
 stage TEXT NOT NULL, request_json TEXT NOT NULL, report_json TEXT,
 error TEXT, model_calls INTEGER NOT NULL DEFAULT 0, usage_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_events (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES research_runs(id),
 created_at TEXT NOT NULL, stage TEXT NOT NULL, detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_checks (
 fact_id INTEGER PRIMARY KEY REFERENCES facts(id), checks_json TEXT NOT NULL,
 fingerprint TEXT NOT NULL UNIQUE, version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calculations (
 id INTEGER PRIMARY KEY, run_id TEXT REFERENCES research_runs(id),
 formula_version TEXT NOT NULL, formula TEXT NOT NULL, input_fact_ids TEXT NOT NULL,
 output_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES research_runs(id),
 statement TEXT NOT NULL, verdict TEXT NOT NULL, evidence_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extraction_cache (
 cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS valuation_runs (
 id TEXT PRIMARY KEY, run_id TEXT REFERENCES research_runs(id),
 input_json TEXT NOT NULL, output_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_snapshots (
 id INTEGER PRIMARY KEY, company TEXT NOT NULL, snapshot_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS valuation_assumptions (
 id INTEGER PRIMARY KEY, valuation_id TEXT NOT NULL REFERENCES valuation_runs(id),
 scenario TEXT NOT NULL, parameter TEXT NOT NULL, value_json TEXT NOT NULL,
 rationale TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS valuation_outputs (
 id INTEGER PRIMARY KEY, valuation_id TEXT NOT NULL REFERENCES valuation_runs(id),
 method TEXT NOT NULL, status TEXT NOT NULL, output_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS peer_sets (
 id INTEGER PRIMARY KEY, run_id TEXT REFERENCES research_runs(id),
 peers_json TEXT NOT NULL, rationale TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_cases (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, expected_json TEXT NOT NULL,
 observed_json TEXT NOT NULL, passed INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS model_probes (
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id,id);
CREATE INDEX IF NOT EXISTS idx_passages_document ON passages(document_id);
