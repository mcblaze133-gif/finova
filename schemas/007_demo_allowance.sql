CREATE TABLE IF NOT EXISTS model_daily_extensions (
 utc_day TEXT PRIMARY KEY,
 extra_attempts INTEGER NOT NULL CHECK(extra_attempts BETWEEN 1 AND 10),
 approved_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 reason TEXT NOT NULL
);
