CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS index_ohlc (
    time        TIMESTAMPTZ      NOT NULL,
    symbol      TEXT             NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT
);

CREATE TABLE IF NOT EXISTS option_ohlc (
    time        TIMESTAMPTZ      NOT NULL,
    symbol      TEXT             NOT NULL,
    expiry      DATE             NOT NULL,
    strike      INTEGER          NOT NULL,
    option_type TEXT             NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT
);

CREATE TABLE IF NOT EXISTS optionchainsnapshot (
    time              TIMESTAMPTZ      NOT NULL,
    underlying_symbol TEXT             NOT NULL,
    expiry            DATE             NOT NULL,
    strike            INTEGER          NOT NULL,
    ce_ltp            DOUBLE PRECISION,
    pe_ltp            DOUBLE PRECISION,
    ce_oi             BIGINT,
    pe_oi             BIGINT,
    ceprevoi          BIGINT,
    peprevoi          BIGINT,
    ce_iv             DOUBLE PRECISION,
    pe_iv             DOUBLE PRECISION,
    ce_delta          DOUBLE PRECISION,
    ce_gamma          DOUBLE PRECISION,
    ce_theta          DOUBLE PRECISION,
    ce_vega           DOUBLE PRECISION,
    pe_delta          DOUBLE PRECISION,
    pe_gamma          DOUBLE PRECISION,
    pe_theta          DOUBLE PRECISION,
    pe_vega           DOUBLE PRECISION,
    ce_bid            DOUBLE PRECISION,
    cebidqty          BIGINT,
    ce_ask            DOUBLE PRECISION,
    ceaskqty          BIGINT,
    pe_bid            DOUBLE PRECISION,
    pebidqty          BIGINT,
    pe_ask            DOUBLE PRECISION,
    peaskqty          BIGINT,
    ceavgprice        DOUBLE PRECISION,
    peavgprice        DOUBLE PRECISION,
    cesecurityid      BIGINT,
    pesecurityid      BIGINT
);

CREATE TABLE IF NOT EXISTS market_depth (
    time        TIMESTAMPTZ      NOT NULL,
    security_id BIGINT           NOT NULL,
    bidprice1   DOUBLE PRECISION,
    bidqty1     BIGINT,
    askprice1   DOUBLE PRECISION,
    askqty1     BIGINT
);

CREATE TABLE IF NOT EXISTS instrument_metadata (
    security_id BIGINT           PRIMARY KEY,
    symbol      TEXT             NOT NULL,
    expiry      DATE,
    strike      INTEGER,
    option_type TEXT,
    lot_size    INTEGER
);

CREATE TABLE IF NOT EXISTS expiry_calendar (
    symbol      TEXT             NOT NULL,
    expiry_date DATE             NOT NULL,
    PRIMARY KEY (symbol, expiry_date)
);

CREATE TABLE IF NOT EXISTS feature_store (
    time        TIMESTAMPTZ      NOT NULL,
    symbol      TEXT             NOT NULL,
    expiry      DATE,
    strike      INTEGER,
    option_type TEXT,
    features    JSONB            NOT NULL,
    label       INTEGER
);

CREATE TABLE IF NOT EXISTS model_predictions (
    time             TIMESTAMPTZ      NOT NULL,
    symbol           TEXT             NOT NULL,
    expiry           DATE,
    strike           INTEGER,
    option_type      TEXT,
    prediction_score DOUBLE PRECISION,
    model_version    TEXT             NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_signals (
    time        TIMESTAMPTZ      NOT NULL,
    symbol      TEXT             NOT NULL,
    expiry      DATE,
    strike      INTEGER,
    option_type TEXT,
    direction   TEXT             NOT NULL,
    confidence  DOUBLE PRECISION,
    stop_loss   DOUBLE PRECISION,
    target      DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS order_logs (
    time        TIMESTAMPTZ      NOT NULL,
    order_id    TEXT             NOT NULL,
    symbol      TEXT             NOT NULL,
    expiry      DATE,
    strike      INTEGER,
    option_type TEXT,
    price       DOUBLE PRECISION,
    qty         INTEGER,
    status      TEXT
);

CREATE TABLE IF NOT EXISTS pnl_history (
    time           TIMESTAMPTZ      NOT NULL,
    realized_pnl   DOUBLE PRECISION,
    unrealized_pnl DOUBLE PRECISION,
    drawdown       DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS model_registry (
    version       TEXT             PRIMARY KEY,
    model_type    TEXT             NOT NULL,
    model_path    TEXT             NOT NULL,
    status        TEXT             NOT NULL DEFAULT 'candidate',
    metrics       JSONB            NOT NULL DEFAULT '{}'::jsonb,
    feature_count INTEGER,
    train_start   TIMESTAMPTZ,
    train_end     TIMESTAMPTZ,
    trained_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    promoted_at   TIMESTAMPTZ,
    notes         TEXT
);

SELECT create_hypertable('index_ohlc', 'time', if_not_exists => TRUE);
SELECT create_hypertable('option_ohlc', 'time', if_not_exists => TRUE);
SELECT create_hypertable('optionchainsnapshot', 'time', if_not_exists => TRUE);
SELECT create_hypertable('market_depth', 'time', if_not_exists => TRUE);
SELECT create_hypertable('feature_store', 'time', if_not_exists => TRUE);
SELECT create_hypertable('model_predictions', 'time', if_not_exists => TRUE);
SELECT create_hypertable('trade_signals', 'time', if_not_exists => TRUE);
SELECT create_hypertable('order_logs', 'time', if_not_exists => TRUE);
SELECT create_hypertable('pnl_history', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_index_ohlc_symbol_time
    ON index_ohlc (symbol, time DESC);

CREATE INDEX IF NOT EXISTS idx_option_ohlc_contract_time
    ON option_ohlc (symbol, expiry, strike, option_type, time DESC);

CREATE INDEX IF NOT EXISTS idx_optionchainsnapshot_contract_time
    ON optionchainsnapshot (underlying_symbol, expiry, strike, time DESC);

CREATE INDEX IF NOT EXISTS idx_market_depth_security_time
    ON market_depth (security_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_feature_store_contract_time
    ON feature_store (symbol, expiry, strike, option_type, time DESC);

CREATE INDEX IF NOT EXISTS idx_model_predictions_contract_time
    ON model_predictions (symbol, expiry, strike, option_type, model_version, time DESC);

CREATE INDEX IF NOT EXISTS idx_trade_signals_symbol_time
    ON trade_signals (symbol, time DESC);

CREATE INDEX IF NOT EXISTS idx_order_logs_order_id_time
    ON order_logs (order_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_pnl_history_time
    ON pnl_history (time DESC);

CREATE INDEX IF NOT EXISTS idx_model_registry_status_trained_at
    ON model_registry (status, trained_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_registry_metrics
    ON model_registry USING GIN (metrics);
