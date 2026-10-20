from pathlib import Path
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "signalai.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    original_url TEXT NOT NULL,
    publication_date TEXT,
    period_start TEXT,
    period_end TEXT,
    retrieved_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    local_path TEXT NOT NULL,
    UNIQUE(company, sha256)
);

CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL
        REFERENCES documents(id),
    pdf_page INTEGER NOT NULL CHECK(pdf_page >= 1),
    text TEXT NOT NULL,
    UNIQUE(document_id, pdf_page)
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    passage_id INTEGER NOT NULL
        REFERENCES passages(id),
    metric TEXT NOT NULL,
    value_decimal TEXT NOT NULL,
    unit TEXT NOT NULL,
    currency TEXT,
    period_start TEXT,
    period_end TEXT NOT NULL,
    accounting_scope TEXT NOT NULL,
    operations_scope TEXT NOT NULL,
    definition TEXT NOT NULL,
    source_quote TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(validation_status IN ('pending', 'validated', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_documents_company
    ON documents(company);

CREATE INDEX IF NOT EXISTS idx_facts_metric_period
    ON facts(metric, period_end);
"""


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def now():
    return datetime.now(timezone.utc).isoformat()


def today_ist():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


@contextmanager
def database():
    connection = connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def rows(sql, parameters=()):
    with database() as db:
        return [dict(row) for row in db.execute(sql, parameters).fetchall()]


def event(run_id, stage, detail):
    with database() as db:
        db.execute('INSERT INTO run_events(run_id,created_at,stage,detail_json) VALUES(?,?,?,?)',
                   (run_id, now(), stage, json.dumps(detail, ensure_ascii=False)))
        db.execute('UPDATE research_runs SET stage=?,updated_at=? WHERE id=?', (stage, now(), run_id))


def initialize():
    for folder in (
        DATA_DIR,
        DATA_DIR / "raw",
        DATA_DIR / "processed",
        PROJECT_DIR / "reports",
        PROJECT_DIR / "workflows",
        PROJECT_DIR / "prompts",
        PROJECT_DIR / "schemas",
        PROJECT_DIR / "tests",
    ):
        folder.mkdir(parents=True, exist_ok=True)

    connection = connect()
    try:
        with connection:
            connection.executescript(SCHEMA)
            for migration in sorted((PROJECT_DIR / 'schemas').glob('*.sql')):
                connection.executescript(migration.read_text(encoding='utf-8'))
    finally:
        connection.close()


if __name__ == "__main__":
    initialize()
