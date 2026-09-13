-- vbtSpike v6 — analytical views
-- These are the intended read interface. Do not query test_runs/ohlcv directly
-- from outside the storage package except for debugging.

CREATE OR REPLACE VIEW comparative AS
    SELECT
        fingerprint,
        params,
        metrics,
        window_start,
        window_end,
        batch_id,
        created_at
    FROM test_runs
    WHERE status = 'complete';

CREATE OR REPLACE VIEW coverage AS
    SELECT
        symbol,
        timeframe,
        MIN(ts)    AS earliest,
        MAX(ts)    AS latest,
        COUNT(*)   AS candles
    FROM ohlcv
    GROUP BY symbol, timeframe;

CREATE OR REPLACE VIEW backtest_run AS
    SELECT
        fingerprint                                                AS backtest_run_id,
        json_extract_string(params, '$.strategy_name')            AS strategy_id,
        json_extract_string(params, '$.symbol')                   AS symbol,
        json_extract_string(params, '$.timeframe')                AS timeframe,
        COALESCE(json_extract_string(params, '$.trade_type'), 'EXIT_TRADE') AS trade_type,
        json_extract_string(params, '$.vectorbt_version')         AS vectorbt_version,
        COALESCE(json_extract_string(params, '$.data_source'), 'duckdb_dump') AS data_source,
        TRY_CAST(json_extract_string(params, '$.random_seed') AS BIGINT) AS random_seed,
        window_start                                               AS date_range_start,
        window_end                                                 AS date_range_end,
        TRY_CAST(json_extract_string(params, '$.initial_cash') AS DOUBLE) AS initial_cash,
        COALESCE(json_extract_string(params, '$.currency'), 'USD') AS currency,
        COALESCE(json_extract_string(params, '$.fee_model'), 'PERCENTAGE') AS fee_model,
        TRY_CAST(json_extract_string(params, '$.fees_value') AS DOUBLE) AS fees_value,
        TRY_CAST(json_extract_string(params, '$.slippage_pct') AS DOUBLE) AS slippage_pct,
        TRY_CAST(json_extract_string(params, '$.sl_stop_pct') AS DOUBLE) AS sl_stop_pct,
        TRY_CAST(json_extract_string(params, '$.tp_stop_pct') AS DOUBLE) AS tp_stop_pct,
        metrics.total_return                                       AS total_return,
        metrics.benchmark_return                                   AS benchmark_return,
        metrics.sharpe_ratio                                       AS sharpe_ratio,
        metrics.sortino_ratio                                      AS sortino_ratio,
        metrics.max_drawdown                                       AS max_drawdown,
        metrics.win_rate                                           AS win_rate,
        metrics.profit_factor                                      AS profit_factor,
        metrics.total_trades                                       AS total_trades,
        batch_id                                                   AS batch_id,
        status                                                     AS status,
        created_at                                                 AS created_at
    FROM test_runs;

CREATE OR REPLACE VIEW run_params AS
    SELECT
        fingerprint                            AS backtest_run_id,
        k                                      AS param_name,
        json_extract_string(params, '$.' || k) AS param_value
    FROM test_runs,
    LATERAL unnest(json_keys(params)) AS t(k);

CREATE OR REPLACE VIEW trade_book AS
    SELECT
        ROW_NUMBER() OVER ()                                       AS trade_id,
        trade.vbt_trade_id                                         AS vbt_trade_id,
        trade.parent_id                                            AS parent_id,
        fingerprint                                                AS backtest_run_id,
        trade.vbt_column                                           AS vbt_column,
        trade.direction                                            AS direction,
        trade.status                                               AS status,
        trade.entry_idx                                            AS entry_idx,
        trade.exit_idx                                             AS exit_idx,
        trade.entry_time                                           AS entry_time,
        trade.exit_time                                            AS exit_time,
        trade.entry_price                                          AS entry_price,
        trade.exit_price                                           AS exit_price,
        trade.size                                                 AS size,
        trade.entry_fees                                           AS entry_fees,
        trade.exit_fees                                            AS exit_fees,
        trade.pnl                                                  AS pnl,
        trade.return_pct                                           AS return_pct,
        trade.holding_bars                                         AS holding_bars,
        trade.holding_seconds                                      AS holding_seconds,
        trade.is_win                                               AS is_win,
        trade.notes                                                AS notes
    FROM (
        SELECT fingerprint, unnest(trades) AS trade
        FROM test_runs
        WHERE status = 'complete'
    );

CREATE OR REPLACE VIEW trades AS
    SELECT * FROM trade_book;


