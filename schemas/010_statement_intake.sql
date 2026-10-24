CREATE TABLE IF NOT EXISTS statement_intake_documents (
 company TEXT NOT NULL, document_id INTEGER NOT NULL REFERENCES documents(id),
 source_sha256 TEXT NOT NULL, parser_version TEXT NOT NULL, checked_at TEXT NOT NULL,
 result_json TEXT NOT NULL, PRIMARY KEY(company,document_id,parser_version)
);
CREATE TABLE IF NOT EXISTS statement_candidates (
 id TEXT PRIMARY KEY, company TEXT NOT NULL, document_id INTEGER NOT NULL REFERENCES documents(id),
 passage_id INTEGER NOT NULL REFERENCES passages(id), candidate_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','stale')),
 created_at TEXT NOT NULL, reviewed_at TEXT, review_note TEXT, library_record_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_statement_review ON statement_candidates(company,status);
