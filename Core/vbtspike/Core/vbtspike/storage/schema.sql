-- vbtSpike v6 — canonical schema
-- Always run a backup snapshot before executing any ALTER TABLE.
-- See Docs/vbSpike-v6-spec.md §6 for the upgrade procedure.

CREATE TABLE IF NOT EXISTS batches (
    batch_id   TEXT PRIMARY KEY,
    started_at TIMESTAMP DEFAULT now(),
    note       TEXT
);

CREATE TABLE IF NOT EXISTS ohlcv (
    symbol    TEXT        NOT NULL,
    timeframe TEXT        NOT NULL,
    ts        TIMESTAMP   NOT NULL,
    open      DOUBLE      NOT NULL,
    high      DOUBLE      NOT NULL,
    low       DOUBLE      NOT NULL,
    close     DOUBLE      NOT NULL,
    volume    DOUBLE      NOT NULL,
    batch_id  TEXT        REFERENCES batches(batch_id),
    PRIMARY KEY (symbol, timeframe, ts)
);

CREATE TYPE run_status AS ENUM ('in_progress', 'complete', 'skipped');
CREATE TYPE trade_side AS ENUM ('buy', 'sell');

CREATE TABLE IF NOT EXISTS test_runs (
    fingerprint  TEXT PRIMARY KEY,
    params       JSON        NOT NULL,
    window_start TIMESTAMP,
    window_end   TIMESTAMP,
    metrics      STRUCT(
        total_return     DOUBLE,
        benchmark_return DOUBLE,
        sharpe_ratio     DOUBLE,
        sortino_ratio    DOUBLE,
        max_drawdown     DOUBLE,
        win_rate         DOUBLE,
        profit_factor    DOUBLE,
        total_trades     BIGINT
    ),
    trades       STRUCT(
        vbt_trade_id     BIGINT,
        parent_id        BIGINT,
        vbt_column       VARCHAR,
        direction        VARCHAR,
        status           VARCHAR,
        entry_idx        BIGINT,
        exit_idx         BIGINT,
        entry_time       TIMESTAMP,
        exit_time        TIMESTAMP,
        entry_price      DOUBLE,
        exit_price       DOUBLE,
        size             DOUBLE,
        entry_fees       DOUBLE,
        exit_fees        DOUBLE,
        pnl              DOUBLE,
        return_pct       DOUBLE,
        holding_bars     BIGINT,
        holding_seconds  BIGINT,
        is_win           BOOLEAN,
        notes            VARCHAR
    )[],
    status       run_status  NOT NULL,
    batch_id     TEXT        REFERENCES batches(batch_id),
    created_at   TIMESTAMP   DEFAULT now()
);
