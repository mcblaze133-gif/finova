CREATE TABLE IF NOT EXISTS company_update_runs (
 id TEXT PRIMARY KEY REFERENCES research_runs(id), company TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL,
 stage TEXT NOT NULL, result_json TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_company_updates_latest ON company_update_runs(company,created_at);
