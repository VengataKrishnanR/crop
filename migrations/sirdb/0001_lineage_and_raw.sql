-- 0001 — Import batches and lossless raw preservation of every worksheet.
--
-- Everything a workbook contains lands here first, cell by cell, with its sheet,
-- row, column, header, cached value and formula text. Normalised tables
-- (0002/0003) point back to these rows by (batch_id, sheet_name, row_no).

CREATE SCHEMA IF NOT EXISTS sirdb;

-- One row per loaded workbook file. The same file (same SHA-256) is loaded once.
CREATE TABLE sirdb.import_batch (
    batch_id        bigserial PRIMARY KEY,
    source_filename text        NOT NULL,
    file_sha256     char(64)    NOT NULL UNIQUE,
    file_size       bigint      NOT NULL,
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    loaded_by       text        NOT NULL,
    status          text        NOT NULL DEFAULT 'LOADING'
                    CHECK (status IN ('LOADING', 'LOADED', 'FAILED')),
    is_current      boolean     NOT NULL DEFAULT false,   -- the batch the views and resolvers use
    summary         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    notes           text
);
-- At most one current batch.
CREATE UNIQUE INDEX import_batch_one_current ON sirdb.import_batch (is_current) WHERE is_current;

CREATE TABLE sirdb.source_sheet (
    batch_id         bigint  NOT NULL REFERENCES sirdb.import_batch ON DELETE CASCADE,
    sheet_name       text    NOT NULL,
    sheet_index      int     NOT NULL,
    used_range       text    NOT NULL,
    max_row          int     NOT NULL,
    max_col          int     NOT NULL,
    headerless       boolean NOT NULL,          -- true: row 1 is data (Sheet1, Sheet2)
    autofilter       text,
    data_validations jsonb   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (batch_id, sheet_name)
);

-- Column order and headers exactly as in the file; header_text NULL = no header.
CREATE TABLE sirdb.source_column (
    batch_id         bigint NOT NULL,
    sheet_name       text   NOT NULL,
    col_index        int    NOT NULL,
    col_letter       text   NOT NULL,
    header_text      text,
    provisional_name text   NOT NULL,           -- internal name; for unheaded columns e.g. col_09_unheaded
    PRIMARY KEY (batch_id, sheet_name, col_index),
    FOREIGN KEY (batch_id, sheet_name) REFERENCES sirdb.source_sheet ON DELETE CASCADE
);

-- Every non-empty row (header rows included, flagged), with its full record in column order.
CREATE TABLE sirdb.source_row (
    batch_id      bigint  NOT NULL,
    sheet_name    text    NOT NULL,
    row_no        int     NOT NULL,             -- the Excel row number
    is_header     boolean NOT NULL DEFAULT false,
    record        jsonb   NOT NULL,             -- [value of col 1, col 2, ...] incl. nulls
    row_sha256    char(64) NOT NULL,
    mapped_to     text,                          -- normalised table holding this row, NULL = not mapped
    map_status    text    NOT NULL DEFAULT 'UNMAPPED'
                  CHECK (map_status IN ('HEADER', 'MAPPED', 'UNMAPPED', 'INFERRED')),
    PRIMARY KEY (batch_id, sheet_name, row_no),
    FOREIGN KEY (batch_id, sheet_name) REFERENCES sirdb.source_sheet ON DELETE CASCADE
);

-- Every non-empty cell: cached value and formula text kept separately.
CREATE TABLE sirdb.source_cell (
    batch_id     bigint NOT NULL,
    sheet_name   text   NOT NULL,
    row_no       int    NOT NULL,
    col_index    int    NOT NULL,
    col_letter   text   NOT NULL,
    value_text   text,                           -- cached value as text (exact)
    value_type   text   NOT NULL,                -- str | int | float | bool | date | datetime
    formula      text,                           -- e.g. =CONCATENATE(B2,"|Import|",N2,"|",O2)
    PRIMARY KEY (batch_id, sheet_name, row_no, col_index),
    FOREIGN KEY (batch_id, sheet_name, row_no) REFERENCES sirdb.source_row ON DELETE CASCADE
);
CREATE INDEX source_cell_formula ON sirdb.source_cell (batch_id, sheet_name) WHERE formula IS NOT NULL;

-- Findings from loading/profiling (warnings, anomalies, unresolved links). Never blocks preservation.
CREATE TABLE sirdb.load_issue (
    issue_id    bigserial PRIMARY KEY,
    batch_id    bigint NOT NULL REFERENCES sirdb.import_batch ON DELETE CASCADE,
    code        text   NOT NULL,
    severity    text   NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    sheet_name  text   NOT NULL,
    row_no      int,
    column_name text,
    value_text  text,
    message     text   NOT NULL,
    basis       text   NOT NULL DEFAULT 'verified' CHECK (basis IN ('verified', 'inferred'))
);
CREATE INDEX load_issue_batch ON sirdb.load_issue (batch_id, sheet_name, row_no);
