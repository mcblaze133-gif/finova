CREATE TABLE IF NOT EXISTS analysis_reports (
 id TEXT PRIMARY KEY,company TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 status TEXT NOT NULL,stage TEXT NOT NULL,research_run_id TEXT,export_id TEXT,pdf_path TEXT,
 snapshot_json TEXT,error TEXT
);
