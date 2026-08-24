"""DuckDB schema definition for the quant platform.

Design notes
------------
- `daily_prices` / `intraday_prices` hold raw-as-downloaded OHLCV. We keep a
  separate `adj_close` column rather than silently adjusting `close`, so the
  backtesting engine can choose adjusted-for-corporate-actions or raw prices
  explicitly (avoids a common source of quiet bugs).
- `index_membership` models point-in-time constituents (`start_date`,
  `end_date`) so historical universes can be reconstructed. If a symbol's
  membership was only ever seeded from *current* constituents, `source`
  is set to 'current_snapshot' and any backtest using it before the seed
  date must be labeled survivorship-biased (see analytics/bias.py).
- `backtest_runs` captures everything needed to reproduce a run later
  (parameters, cost assumptions, dataset window, software version, seed).
"""
from __future__ import annotations

import duckdb

SCHEMA_STATEMENTS: list[str] = [
    # ---------------------------------------------------------------------- users
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id       VARCHAR PRIMARY KEY,
        username      VARCHAR UNIQUE NOT NULL,
        password_hash VARCHAR NOT NULL,
        password_salt VARCHAR NOT NULL,
        created_at    TIMESTAMP DEFAULT current_timestamp
    );
    """,
    # ------------------------------------------------------------------- sessions
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token      VARCHAR PRIMARY KEY,
        user_id    VARCHAR NOT NULL,
        created_at TIMESTAMP DEFAULT current_timestamp,
        expires_at TIMESTAMP NOT NULL
    );
    """,
    # ---------------------------------------------------------------- instruments
    """
    CREATE TABLE IF NOT EXISTS instruments (
        symbol              VARCHAR PRIMARY KEY,   -- provider symbol, e.g. RELIANCE.NS
        base_symbol         VARCHAR,                -- exchange-native symbol, e.g. RELIANCE
        exchange            VARCHAR,                -- NSE / BSE
        name                VARCHAR,
        isin                VARCHAR,
        sector              VARCHAR,
        industry            VARCHAR,
        instrument_type     VARCHAR DEFAULT 'EQUITY', -- EQUITY / INDEX / ETF
        first_listed_date   DATE,
        is_active           BOOLEAN DEFAULT TRUE,
        added_at            TIMESTAMP DEFAULT current_timestamp
    );
    """,
    # -------------------------------------------------------------- daily_prices
    """
    CREATE TABLE IF NOT EXISTS daily_prices (
        symbol      VARCHAR NOT NULL,
        date        DATE NOT NULL,
        open        DOUBLE,
        high        DOUBLE,
        low         DOUBLE,
        close       DOUBLE,
        adj_close   DOUBLE,
        volume      BIGINT,
        source      VARCHAR,
        inserted_at TIMESTAMP DEFAULT current_timestamp,
        PRIMARY KEY (symbol, date)
    );
    """,
    # ----------------------------------------------------------- intraday_prices
    """
    CREATE TABLE IF NOT EXISTS intraday_prices (
        symbol      VARCHAR NOT NULL,
        ts          TIMESTAMP NOT NULL,
        interval    VARCHAR NOT NULL,   -- e.g. '5m', '15m', '1h'
        open        DOUBLE,
        high        DOUBLE,
        low         DOUBLE,
        close       DOUBLE,
        volume      BIGINT,
        source      VARCHAR,
        inserted_at TIMESTAMP DEFAULT current_timestamp,
        PRIMARY KEY (symbol, ts, interval)
    );
    """,
    # --------------------------------------------------------- corporate_actions
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        symbol            VARCHAR NOT NULL,
        ex_date           DATE NOT NULL,
        action_type       VARCHAR NOT NULL, -- DIVIDEND / SPLIT / BONUS / RIGHTS / DELISTING / SYMBOL_CHANGE
        ratio_numerator   DOUBLE,
        ratio_denominator DOUBLE,
        dividend_amount   DOUBLE,
        new_symbol        VARCHAR,
        notes             VARCHAR,
        source            VARCHAR,
        inserted_at       TIMESTAMP DEFAULT current_timestamp,
        PRIMARY KEY (symbol, ex_date, action_type)
    );
    """,
    # ----------------------------------------------------------- index_membership
    """
    CREATE TABLE IF NOT EXISTS index_membership (
        index_name  VARCHAR NOT NULL,
        symbol      VARCHAR NOT NULL,
        start_date  DATE NOT NULL,
        end_date    DATE,               -- NULL = still a member
        source      VARCHAR,             -- 'current_snapshot' | 'historical_verified'
        inserted_at TIMESTAMP DEFAULT current_timestamp,
        PRIMARY KEY (index_name, symbol, start_date)
    );
    """,
    # ------------------------------------------------------------- data_metadata
    """
    CREATE TABLE IF NOT EXISTS data_metadata (
        symbol          VARCHAR NOT NULL,
        data_type       VARCHAR NOT NULL, -- daily | intraday | corporate_actions
        first_date      DATE,
        last_date       DATE,
        row_count       BIGINT,
        missing_sessions BIGINT DEFAULT 0,
        duplicate_rows   BIGINT DEFAULT 0,
        invalid_ohlc_rows BIGINT DEFAULT 0,
        suspicious_moves  BIGINT DEFAULT 0,
        status          VARCHAR,           -- OK | WARNING | ERROR
        notes           VARCHAR,
        last_updated_at TIMESTAMP DEFAULT current_timestamp,
        PRIMARY KEY (symbol, data_type)
    );
    """,
    # ------------------------------------------------------------- backtest_runs
    """
    CREATE SEQUENCE IF NOT EXISTS backtest_run_seq START 1;
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        backtest_id         VARCHAR PRIMARY KEY,
        created_at          TIMESTAMP DEFAULT current_timestamp,
        strategy_name       VARCHAR,
        strategy_version    VARCHAR,
        parameters_json     VARCHAR,
        universe            VARCHAR,
        start_date          DATE,
        end_date            DATE,
        initial_capital     DOUBLE,
        cost_model_json     VARCHAR,
        slippage_bps        DOUBLE,
        benchmark_symbol    VARCHAR,
        random_seed         INTEGER,
        software_version    VARCHAR,
        dataset_snapshot_at TIMESTAMP,
        survivorship_biased BOOLEAN,
        status              VARCHAR,   -- COMPLETED | FAILED
        notes               VARCHAR
    );
    """,
    # ----------------------------------------------------------- backtest_trades
    """
    CREATE SEQUENCE IF NOT EXISTS backtest_trade_seq START 1;
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_trades (
        trade_id          BIGINT PRIMARY KEY DEFAULT nextval('backtest_trade_seq'),
        backtest_id       VARCHAR NOT NULL,
        symbol            VARCHAR NOT NULL,
        side              VARCHAR NOT NULL,   -- BUY | SELL | SHORT | COVER
        signal_date       DATE NOT NULL,
        execution_date    DATE NOT NULL,
        execution_price   DOUBLE NOT NULL,
        quantity           DOUBLE NOT NULL,
        gross_amount      DOUBLE NOT NULL,
        costs             DOUBLE NOT NULL,
        net_amount        DOUBLE NOT NULL,
        realized_pnl      DOUBLE,
        holding_period_days INTEGER,
        exit_reason       VARCHAR
    );
    """,
    # ------------------------------------------------------- backtest_equity_curve
    """
    CREATE TABLE IF NOT EXISTS backtest_equity_curve (
        backtest_id    VARCHAR NOT NULL,
        date           DATE NOT NULL,
        cash           DOUBLE,
        holdings_value DOUBLE,
        total_value    DOUBLE,
        daily_return   DOUBLE,
        drawdown       DOUBLE,
        PRIMARY KEY (backtest_id, date)
    );
    """,
    # -------------------------------------------------------------- paper_accounts
    """
    CREATE TABLE IF NOT EXISTS paper_accounts (
        account_id      VARCHAR PRIMARY KEY,
        user_id         VARCHAR,
        name            VARCHAR NOT NULL,
        initial_capital DOUBLE NOT NULL,
        cash            DOUBLE NOT NULL,
        created_at      TIMESTAMP DEFAULT current_timestamp
    );
    """,
    # ------------------------------------------------------------- paper_positions
    """
    CREATE TABLE IF NOT EXISTS paper_positions (
        account_id VARCHAR NOT NULL,
        symbol     VARCHAR NOT NULL,
        quantity   DOUBLE NOT NULL,
        avg_price  DOUBLE NOT NULL,
        opened_at  TIMESTAMP,
        PRIMARY KEY (account_id, symbol)
    );
    """,
    # ---------------------------------------------------------------- paper_trades
    """
    CREATE TABLE IF NOT EXISTS paper_trades (
        trade_id           VARCHAR PRIMARY KEY,
        account_id         VARCHAR NOT NULL,
        symbol             VARCHAR NOT NULL,
        side               VARCHAR NOT NULL,
        execution_date     TIMESTAMP NOT NULL,
        execution_price    DOUBLE NOT NULL,
        quantity           DOUBLE NOT NULL,
        gross_amount       DOUBLE NOT NULL,
        costs              DOUBLE NOT NULL,
        net_amount         DOUBLE NOT NULL,
        realized_pnl       DOUBLE,
        holding_period_days DOUBLE,
        exit_reason        VARCHAR,
        quote_source       VARCHAR
    );
    """,
    # ------------------------------------------------------- paper_equity_snapshots
    """
    CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
        account_id     VARCHAR NOT NULL,
        snapshot_at    TIMESTAMP NOT NULL,
        cash           DOUBLE,
        holdings_value DOUBLE,
        total_value    DOUBLE,
        PRIMARY KEY (account_id, snapshot_at)
    );
    """,
    # ----------------------------------------------------------- saved_strategies
    """
    CREATE TABLE IF NOT EXISTS saved_strategies (
        strategy_id     VARCHAR PRIMARY KEY,
        name            VARCHAR NOT NULL,
        kind            VARCHAR NOT NULL,  -- 'rule_based' | 'custom_code'
        definition_json VARCHAR NOT NULL,   -- entry/exit conditions, or source code
        risk_json       VARCHAR,
        created_at      TIMESTAMP DEFAULT current_timestamp,
        notes           VARCHAR
    );
    """,
    # -------------------------------------------------------- strategy_parameters
    """
    CREATE TABLE IF NOT EXISTS strategy_parameters (
        id                  BIGINT PRIMARY KEY DEFAULT nextval('backtest_trade_seq'),
        backtest_id         VARCHAR,
        strategy_name       VARCHAR,
        param_name          VARCHAR,
        param_value         VARCHAR,
        param_type          VARCHAR,
        is_optimized        BOOLEAN DEFAULT FALSE,
        optimization_run_id VARCHAR
    );
    """,
    # -------------------------------------------------------------- misc indexes
    "CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);",
    "CREATE INDEX IF NOT EXISTS idx_corp_actions_symbol ON corporate_actions(symbol);",
    "CREATE INDEX IF NOT EXISTS idx_index_membership_index ON index_membership(index_name);",
    "CREATE INDEX IF NOT EXISTS idx_backtest_trades_backtest ON backtest_trades(backtest_id);",
]


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    for stmt in SCHEMA_STATEMENTS:
        con.execute(stmt)
