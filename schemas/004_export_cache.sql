CREATE TABLE IF NOT EXISTS excel_export_cache (
 input_hash TEXT PRIMARY KEY,
 export_id TEXT NOT NULL REFERENCES excel_exports(id),
 workbook_sha256 TEXT NOT NULL
);
