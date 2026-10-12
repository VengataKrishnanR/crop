-- 0003 — The business rules (Import) and their attribute-level lines (SIR Reference).
--
-- Every source value is kept as written (*_raw / the plain column). Where a value needs
-- normalising (text dates, numbers, Y/N flags, lists), the normalised value sits beside it
-- with *_issue saying why it could not be normalised. Nothing is repaired silently.

CREATE TABLE sirdb.import_rule (
    batch_id                   bigint NOT NULL,
    source_sheet               text   NOT NULL DEFAULT 'Import' CHECK (source_sheet = 'Import'),
    source_row_no              int    NOT NULL,
    -- A..O: business columns, as in the file
    region                     text,
    country                    text,
    shipment_type              text,                      -- B2B/B2C (C2C also occurs)
    effective_date_raw         text,
    effective_date             date,
    effective_date_issue       text,
    expiry_date_raw            text,
    expiry_date                date,
    expiry_date_issue          text,
    network_product_code_raw   text,
    value_basis                text,                      -- DV | IV
    currency                   text,
    min_value_raw              text,
    min_value                  numeric,
    max_value_raw              text,
    max_value                  numeric,
    min_weight_raw             text,
    min_weight                 numeric,
    max_weight_raw             text,
    max_weight                 numeric,
    other_logic                text,                      -- inert text, never executed
    country_hold_code          text,                      -- numbers kept as text ('1', '3')
    global_hold_code           text,
    -- P: Document Reference (key into SIR Reference) — value and how it was produced
    document_reference         text,
    document_reference_formula text,
    document_reference_kind    text NOT NULL CHECK (document_reference_kind IN ('FORMULA', 'LITERAL', 'EMPTY')),
    -- Q: SIRG Document Reference (key into Technical SIRG) and its parsed parts
    sirg_document_reference    text,
    sirg_ref_country           text,
    sirg_ref_direction         text,                      -- 'Import' in every row
    sirg_ref_sirg_cd           text,
    -- Derived classifications (documented, reproducible)
    is_document_ref_placeholder boolean NOT NULL,
    is_sirg_ref_placeholder     boolean NOT NULL,
    rule_generation            text NOT NULL CHECK (rule_generation IN ('HOLD_CODE', 'SIRG', 'UNCLASSIFIED')),
    PRIMARY KEY (batch_id, source_row_no),
    FOREIGN KEY (batch_id, source_sheet, source_row_no) REFERENCES sirdb.source_row ON DELETE CASCADE
);
CREATE INDEX import_rule_sirg ON sirdb.import_rule (batch_id, sirg_ref_country, sirg_ref_sirg_cd);
CREATE INDEX import_rule_docref ON sirdb.import_rule (batch_id, document_reference);

-- Network Product Code split into its codes, in order (the raw list stays on import_rule).
CREATE TABLE sirdb.import_rule_product_code (
    batch_id       bigint NOT NULL,
    source_row_no  int    NOT NULL,
    position       int    NOT NULL,
    product_code   text   NOT NULL,
    PRIMARY KEY (batch_id, source_row_no, position),
    FOREIGN KEY (batch_id, source_row_no) REFERENCES sirdb.import_rule ON DELETE CASCADE
);

CREATE TABLE sirdb.sir_reference (
    batch_id                    bigint NOT NULL,
    source_sheet                text   NOT NULL DEFAULT 'SIR Reference' CHECK (source_sheet = 'SIR Reference'),
    source_row_no               int    NOT NULL,
    document_reference          text,                     -- A (cached value)
    document_reference_formula  text,                     -- A formula, e.g. =IF(Import!P4<>0,Import!P4,"")
    formula_target_import_row   int,                      -- the Import row the formula points at, by position
    sir_document_reference      text,                     -- B: Country|Import|SIRGCd|CmptNm
    sdr_country                 text,
    sdr_direction               text,
    sdr_sirg_cd                 text,
    sdr_cmpt_nm                 text,
    waived_if_whitelisted_raw   text,                     -- C
    waived_if_whitelisted       boolean,                  -- Y -> true, N -> false, else NULL (+ issue)
    waived_to_validate_raw      text,                     -- D ('4' occurs once)
    waived_to_validate          boolean,
    check_if_service_code       text,                     -- E
    cmpt_nm                     text,                     -- F
    sir_technical_id            text,                     -- G
    attribute_id_raw            text,                     -- H as written ('&&' / '&' separated)
    col_09_unheaded             text,                     -- I: no header in the file (provisional: attribute labels, Q-01)
    is_document_ref_placeholder boolean NOT NULL,
    is_sdr_placeholder          boolean NOT NULL,
    PRIMARY KEY (batch_id, source_row_no),
    FOREIGN KEY (batch_id, source_sheet, source_row_no) REFERENCES sirdb.source_row ON DELETE CASCADE
);
CREATE INDEX sir_reference_docref ON sirdb.sir_reference (batch_id, document_reference);
CREATE INDEX sir_reference_sdr ON sirdb.sir_reference (batch_id, sdr_country, sdr_sirg_cd);

-- AttributeID split into one row per id, with the unheaded column's entry at the same position.
CREATE TABLE sirdb.sir_reference_attribute (
    batch_id          bigint NOT NULL,
    source_row_no     int    NOT NULL,
    position          int    NOT NULL,
    attribute_id      text   NOT NULL,
    col_09_entry      text,                               -- provisional label (Q-01); NULL if counts differ
    PRIMARY KEY (batch_id, source_row_no, position),
    FOREIGN KEY (batch_id, source_row_no) REFERENCES sirdb.sir_reference ON DELETE CASCADE
);
CREATE INDEX sir_reference_attribute_id ON sirdb.sir_reference_attribute (batch_id, attribute_id);

-- Business rules authored outside the workbook (e.g. by the onboarding platform), validated
-- against the catalogs before they may appear in the final Import output. Versioned, never edited in place.
CREATE TABLE sirdb.rule_proposal (
    proposal_id          bigserial PRIMARY KEY,
    supersedes_id        bigint REFERENCES sirdb.rule_proposal,
    status               text NOT NULL DEFAULT 'DRAFT'
                         CHECK (status IN ('DRAFT', 'VALIDATED', 'REJECTED', 'APPROVED', 'RETIRED')),
    region               text,
    country              text NOT NULL,
    shipment_type        text,
    effective_date       date,
    expiry_date          date,
    network_product_code text,
    value_basis          text,
    currency             text,
    min_value            numeric,
    max_value            numeric,
    min_weight           numeric,
    max_weight           numeric,
    other_logic          text,
    country_hold_code    text,
    global_hold_code     text,
    processing_type      text NOT NULL DEFAULT 'IMP_CLR',
    sirg_cd              text,
    document_reference   text,
    validation           jsonb,                           -- last validation result (errors / warnings)
    validated_batch_id   bigint REFERENCES sirdb.import_batch,
    created_by           text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    approved_by          text,
    approved_at          timestamptz
);
