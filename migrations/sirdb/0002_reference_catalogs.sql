-- 0002 — Reference catalogs: Technical SIR, Technical SIRG, Other Logic, Validation lists,
-- the Export template and the headerless Sheet1 record.
--
-- Catalog rows are versioned by batch: every loaded workbook keeps its own copy,
-- so two versions can be compared and nothing is overwritten in place.
-- Every row carries (batch_id, source_sheet, source_row_no) back to sirdb.source_row.

-- Technical SIR: the component catalog. SIR Technical ID is the key; CmptNm is NOT unique
-- (e.g. PPYComposed appears 31 times with different ids), so it carries no unique constraint.
CREATE TABLE sirdb.technical_sir (
    batch_id          bigint NOT NULL,
    source_sheet      text   NOT NULL DEFAULT 'Technical SIR' CHECK (source_sheet = 'Technical SIR'),
    source_row_no     int    NOT NULL,
    sir_technical_id  text   NOT NULL,
    cmpt_nm           text   NOT NULL,
    nm                text,
    dsc               text,
    PRIMARY KEY (batch_id, sir_technical_id),
    UNIQUE (batch_id, source_row_no),
    FOREIGN KEY (batch_id, source_sheet, source_row_no) REFERENCES sirdb.source_row ON DELETE CASCADE
);
CREATE INDEX technical_sir_cmpt ON sirdb.technical_sir (batch_id, cmpt_nm);

-- Technical SIRG: country × processing type × requirement group → component + SIR id.
-- The lookup key (country, processing type, SIRG code) is unique in practice except for one exact
-- duplicate record (AU·GSTE rows 877/880), so it is indexed, not constrained; resolvers report >1 match.
CREATE TABLE sirdb.technical_sirg (
    batch_id          bigint NOT NULL,
    source_sheet      text   NOT NULL DEFAULT 'Technical SIRG' CHECK (source_sheet = 'Technical SIRG'),
    source_row_no     int    NOT NULL,
    sirg_technical_id text   NOT NULL,
    sirg_cd           text   NOT NULL,
    sirg_nm           text,
    sirg_dsc          text,                              -- empty on every row today; kept
    dhl_ctry_cd       text   NOT NULL,
    processing_type   text   NOT NULL,
    cmpt_nm           text   NOT NULL,
    sir_technical_id  text   NOT NULL,
    PRIMARY KEY (batch_id, source_row_no),
    FOREIGN KEY (batch_id, source_sheet, source_row_no) REFERENCES sirdb.source_row ON DELETE CASCADE,
    -- Every SIR id exists in Technical SIR of the same batch (verified: 0 exceptions).
    FOREIGN KEY (batch_id, sir_technical_id) REFERENCES sirdb.technical_sir (batch_id, sir_technical_id)
);
CREATE INDEX technical_sirg_key ON sirdb.technical_sirg (batch_id, dhl_ctry_cd, processing_type, sirg_cd);
CREATE INDEX technical_sirg_sir ON sirdb.technical_sirg (batch_id, sir_technical_id);

-- Other Logic palette: inert text. Never executed.
CREATE TABLE sirdb.logic_expression (
    batch_id       bigint NOT NULL,
    source_sheet   text   NOT NULL DEFAULT 'Other Logic' CHECK (source_sheet = 'Other Logic'),
    source_row_no  int    NOT NULL,
    expression     text   NOT NULL,                  -- exactly as in the cell (spaces kept)
    description    text,                             -- only when confirmed by the business
    PRIMARY KEY (batch_id, source_row_no),
    FOREIGN KEY (batch_id, source_sheet, source_row_no) REFERENCES sirdb.source_row ON DELETE CASCADE
);

-- Reference lists (each Validation column, and Sheet2) with their origin. Lists are never merged.
CREATE TABLE sirdb.reference_list (
    list_id        bigserial PRIMARY KEY,
    batch_id       bigint NOT NULL REFERENCES sirdb.import_batch ON DELETE CASCADE,
    list_name      text   NOT NULL,                  -- e.g. 'Validation.Currency List', 'Sheet2'
    origin_sheet   text   NOT NULL,
    origin_col     int    NOT NULL,
    origin_header  text,                             -- NULL for a headerless list (Sheet2)
    UNIQUE (batch_id, list_name)
);
CREATE TABLE sirdb.reference_list_item (
    list_id           bigint NOT NULL REFERENCES sirdb.reference_list ON DELETE CASCADE,
    position          int    NOT NULL,
    source_row_no     int    NOT NULL,
    value_raw         text   NOT NULL,               -- as in the file, e.g. 'SK ' with its space
    value_normalized  text   NOT NULL,               -- trimmed
    normalization     text,                          -- why value_normalized differs, if it does
    PRIMARY KEY (list_id, position)
);
CREATE INDEX reference_list_item_value ON sirdb.reference_list_item (list_id, value_normalized);

-- Template headers (the Export sheet) — kept as a definition, purpose unconfirmed (Q-09).
CREATE TABLE sirdb.template_column (
    batch_id      bigint NOT NULL REFERENCES sirdb.import_batch ON DELETE CASCADE,
    template_name text   NOT NULL,                   -- 'Export'
    position      int    NOT NULL,
    header_text   text   NOT NULL,
    in_import     boolean NOT NULL,                  -- the same header exists on Import
    PRIMARY KEY (batch_id, template_name, position)
);

-- Rows whose schema is inferred, not declared (Sheet1: shaped like a Technical SIRG row).
CREATE TABLE sirdb.inferred_record (
    batch_id       bigint NOT NULL,
    source_sheet   text   NOT NULL,
    source_row_no  int    NOT NULL,
    inferred_as    text   NOT NULL,                  -- e.g. 'technical_sirg'
    fields         jsonb  NOT NULL,                  -- values named by the inferred schema
    evidence       text   NOT NULL,
    PRIMARY KEY (batch_id, source_sheet, source_row_no),
    FOREIGN KEY (batch_id, source_sheet, source_row_no) REFERENCES sirdb.source_row ON DELETE CASCADE
);
