CREATE TABLE IF NOT EXISTS model_registry (
    version       TEXT PRIMARY KEY,
    model_type    TEXT NOT NULL,
    model_path    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'candidate',
    metrics       JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_count INTEGER,
    train_start   TIMESTAMPTZ,
    train_end     TIMESTAMPTZ,
    trained_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at   TIMESTAMPTZ,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_registry_status_trained_at
    ON model_registry (status, trained_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_registry_metrics
    ON model_registry USING GIN (metrics);
