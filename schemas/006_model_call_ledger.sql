CREATE TABLE IF NOT EXISTS model_call_ledger (
 run_id TEXT NOT NULL REFERENCES research_runs(id),
 utc_day TEXT NOT NULL,
 calls INTEGER NOT NULL CHECK(calls >= 0),
 PRIMARY KEY(run_id,utc_day)
);
