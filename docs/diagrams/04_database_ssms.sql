/*
VISUALIZATION MIRROR FOR SQL SERVER / SSMS ONLY.
Source of truth: src/aiomql/ledger/sqlite.py and ledger/models.py (2026-10-08).
The application continues to use SQLite. This is not a migration or runtime backend.

Create and select an EMPTY TEST DATABASE yourself before running this script.
No database is created/dropped, no credentials/data are included, and no application
configuration is modified. Re-running against populated tables fails intentionally.

Type mapping / unavoidable mirror differences:
  SQLite TEXT UUID -> VARCHAR(36); integer identifiers -> VARCHAR(128).
  SQLite unbounded namespace/server -> NVARCHAR(128) for indexable mirror keys.
  These bounds are visualization choices, NOT new Python/SQLite validation rules.
  SQLite Decimal TEXT -> NVARCHAR(MAX), never REAL/FLOAT/DECIMAL conversion.
  Canonical raw JSON -> NVARCHAR(MAX) (Unicode UTF-16 in SQL Server; SQLite uses TEXT).
  SHA256 hex -> VARCHAR(64); ISO UTC timestamps -> NVARCHAR(64), still text.
  SQLite INTEGER -> BIGINT (including enum codes / normalizer_version).
  BIN2 collation approximates SQLite's default case-sensitive BINARY key comparisons.
  SQL Server trailing-space comparison semantics can still differ from SQLite.
  SQL Server PK requires NOT NULL. SQLite source declares bare TEXT PRIMARY KEY
  in ordinary rowid tables; repository/model usage supplies non-null UUIDs.
  No new CHECK constraints, JSON validation constraints, cascade rules or indexes.

SQLiteDealRepository enables PRAGMA foreign_keys=ON on EACH repository connection.
External SQLite connections must enable it themselves. SQL Server FKs below are
enabled normally; all use NO ACTION, matching the absence of source cascade rules.
SSMS may create its own diagram-support objects after this script; those objects
are SSMS tooling, not Deal Ledger schema.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME() IN (N'master', N'model', N'msdb', N'tempdb')
BEGIN
    THROW 50001, 'Select an empty test database before creating the visualization mirror.', 1;
END;

IF EXISTS (SELECT 1 FROM sys.tables WHERE is_ms_shipped = 0)
BEGIN
    THROW 50002, 'The visualization mirror requires an empty test database. No tables were changed.', 1;
END;

BEGIN TRY
    BEGIN TRANSACTION;

    CREATE TABLE dbo.ledger_accounts
    (
        mt5_account_id VARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
        broker_namespace NVARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
        server NVARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
        login VARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
        company_observed NVARCHAR(MAX) NOT NULL,
        trade_mode BIGINT NOT NULL,
        CONSTRAINT PK_ledger_accounts PRIMARY KEY (mt5_account_id),
        CONSTRAINT UQ_ledger_accounts_context UNIQUE (broker_namespace, server, login)
    );

    CREATE TABLE dbo.deals
    (
        id VARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
        mt5_account_id VARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
        deal_ticket VARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
        order_ticket VARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
        position_id VARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
        symbol NVARCHAR(MAX) NOT NULL,
        deal_type BIGINT NOT NULL,
        deal_entry BIGINT NOT NULL,
        magic VARCHAR(128) NOT NULL,
        volume NVARCHAR(MAX) NOT NULL,
        price NVARCHAR(MAX) NOT NULL,
        commission NVARCHAR(MAX) NOT NULL,
        swap NVARCHAR(MAX) NOT NULL,
        profit NVARCHAR(MAX) NOT NULL,
        broker_fee NVARCHAR(MAX) NOT NULL,
        broker_time_seconds BIGINT NOT NULL,
        executed_at_msc BIGINT NOT NULL,
        reason BIGINT NULL,
        sl NVARCHAR(MAX) NULL,
        tp NVARCHAR(MAX) NULL,
        comment NVARCHAR(MAX) NULL,
        external_id NVARCHAR(MAX) NULL,
        raw_payload NVARCHAR(MAX) NOT NULL,
        payload_hash VARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
        normalizer_version BIGINT NOT NULL,
        first_seen_at NVARCHAR(64) NOT NULL,
        ingestion_id NVARCHAR(MAX) NOT NULL,
        CONSTRAINT PK_deals PRIMARY KEY (id),
        CONSTRAINT FK_deals_account FOREIGN KEY (mt5_account_id)
            REFERENCES dbo.ledger_accounts (mt5_account_id)
            ON DELETE NO ACTION ON UPDATE NO ACTION,
        CONSTRAINT UQ_deals_account_ticket UNIQUE (mt5_account_id, deal_ticket)
    );

    -- Only the two explicitly declared non-unique indexes from SQLite source.
    CREATE INDEX idx_deals_order ON dbo.deals (mt5_account_id, order_ticket);
    CREATE INDEX idx_deals_position ON dbo.deals (mt5_account_id, position_id);

    CREATE TABLE dbo.deal_observations
    (
        id VARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
        deal_id VARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
        payload_hash VARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
        raw_payload NVARCHAR(MAX) NOT NULL,
        observed_at NVARCHAR(64) NOT NULL,
        ingestion_id NVARCHAR(MAX) NOT NULL,
        normalizer_version BIGINT NOT NULL,
        CONSTRAINT PK_deal_observations PRIMARY KEY (id),
        CONSTRAINT FK_deal_observations_deal FOREIGN KEY (deal_id)
            REFERENCES dbo.deals (id)
            ON DELETE NO ACTION ON UPDATE NO ACTION,
        CONSTRAINT UQ_deal_observations_payload UNIQUE (deal_id, payload_hash)
    );

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
