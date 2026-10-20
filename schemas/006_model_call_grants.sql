CREATE TABLE IF NOT EXISTS model_call_grants (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id), utc_day TEXT NOT NULL,
 approved_at TEXT NOT NULL, remaining_calls INTEGER NOT NULL CHECK(remaining_calls BETWEEN 0 AND 2),
 reason TEXT NOT NULL
);
