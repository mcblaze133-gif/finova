CREATE TABLE IF NOT EXISTS library_records (
 id TEXT PRIMARY KEY, company TEXT NOT NULL, record_json TEXT NOT NULL,
 file_hash TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_company ON library_records(company);
CREATE TABLE IF NOT EXISTS driver_assumptions (
 id TEXT PRIMARY KEY, company TEXT NOT NULL, driver TEXT NOT NULL, scenario TEXT NOT NULL,
 record_json TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(company,driver,scenario)
);
CREATE TABLE IF NOT EXISTS assumption_changes (
 id INTEGER PRIMARY KEY, assumption_id TEXT NOT NULL, previous_json TEXT,
 next_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS excel_exports (
 id TEXT PRIMARY KEY, company TEXT NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL, input_json TEXT NOT NULL, workbook_path TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS library_documents (
 id INTEGER PRIMARY KEY, company TEXT NOT NULL, relative_path TEXT NOT NULL,
 document_id INTEGER NOT NULL REFERENCES documents(id), source_date TEXT,
 UNIQUE(company,relative_path,document_id)
);
