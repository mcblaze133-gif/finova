CREATE TABLE IF NOT EXISTS model_recording_topups (
 approval_id TEXT PRIMARY KEY,
 utc_day TEXT NOT NULL,
 extra_attempts INTEGER NOT NULL CHECK(extra_attempts BETWEEN 1 AND 20),
 approved_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 reason TEXT NOT NULL
);
