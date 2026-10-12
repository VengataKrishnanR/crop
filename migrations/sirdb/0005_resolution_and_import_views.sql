-- 0005 — Resolution views and the final Import dataset.
--
-- The downstream application reads ONLY sirdb.v_import_final (17 Import columns, in order).
-- The other views exist for validation, reconciliation and maintenance.

CREATE VIEW sirdb.v_current_batch AS
SELECT batch_id FROM sirdb.import_batch WHERE is_current;

-- SIRG resolution for each Import rule: how many Technical SIRG rows match
-- (country, IMP_CLR, SIRG code) — 0, 1 or more — and, when exactly one, what it resolves to.
CREATE VIEW sirdb.v_import_rule_sirg AS
WITH m AS (
    SELECT r.batch_id, r.source_row_no,
           count(g.*)                              AS sirg_matches,
           count(DISTINCT (g.sirg_technical_id, g.cmpt_nm, g.sir_technical_id)) AS distinct_targets,
           min(g.sirg_technical_id)                AS sirg_technical_id,
           min(g.sirg_nm)                          AS sirg_nm,
           min(g.cmpt_nm)                          AS cmpt_nm,
           min(g.sir_technical_id)                 AS sir_technical_id,
           array_agg(g.source_row_no ORDER BY g.source_row_no) FILTER (WHERE g.source_row_no IS NOT NULL)
                                                   AS sirg_source_rows
    FROM sirdb.import_rule r
    LEFT JOIN sirdb.technical_sirg g
           ON g.batch_id = r.batch_id
          AND g.dhl_ctry_cd = r.sirg_ref_country
          AND g.processing_type = 'IMP_CLR'
          AND g.sirg_cd = r.sirg_ref_sirg_cd
    GROUP BY r.batch_id, r.source_row_no
)
SELECT r.batch_id, r.source_row_no, r.country, r.sirg_document_reference, r.is_sirg_ref_placeholder,
       m.sirg_matches, m.distinct_targets, m.sirg_source_rows,
       CASE WHEN r.is_sirg_ref_placeholder OR r.sirg_ref_sirg_cd IS NULL THEN 'NOT_APPLICABLE'
            WHEN m.sirg_matches = 0 THEN 'NOT_FOUND'
            WHEN m.distinct_targets > 1 THEN 'AMBIGUOUS'
            WHEN m.sirg_matches > 1 THEN 'DUPLICATE_RECORDS'   -- identical rows: same target
            ELSE 'RESOLVED' END                       AS sirg_status,
       CASE WHEN m.distinct_targets = 1 THEN m.sirg_technical_id END AS sirg_technical_id,
       CASE WHEN m.distinct_targets = 1 THEN m.sirg_nm END           AS sirg_nm,
       CASE WHEN m.distinct_targets = 1 THEN m.cmpt_nm END           AS cmpt_nm,
       CASE WHEN m.distinct_targets = 1 THEN m.sir_technical_id END  AS sir_technical_id,
       EXISTS (SELECT 1 FROM sirdb.technical_sir s
               WHERE s.batch_id = r.batch_id AND s.sir_technical_id = m.sir_technical_id
                 AND s.cmpt_nm = m.cmpt_nm)          AS sir_pair_in_catalog
FROM sirdb.import_rule r JOIN m USING (batch_id, source_row_no);

-- SIR Reference lines linked to each Import rule, by either documented join:
--   LEGACY: sir_reference.document_reference = import_rule.document_reference (non-placeholder)
--   SIRG:   sir_reference.(country, SIRG code) from its SIR Document Reference = import_rule's SIRG reference
CREATE VIEW sirdb.v_import_rule_sir_reference AS
SELECT r.batch_id, r.source_row_no AS import_row, s.source_row_no AS sir_reference_row,
       CASE WHEN s.document_reference = r.document_reference AND NOT r.is_document_ref_placeholder
            THEN 'LEGACY_DOCUMENT_REFERENCE' ELSE 'SIRG_DOCUMENT_REFERENCE' END AS join_style,
       s.cmpt_nm, s.sir_technical_id, s.waived_if_whitelisted, s.waived_to_validate,
       s.check_if_service_code, s.attribute_id_raw, s.col_09_unheaded
FROM sirdb.import_rule r
JOIN sirdb.sir_reference s
  ON s.batch_id = r.batch_id
 AND (   (NOT r.is_document_ref_placeholder AND s.document_reference = r.document_reference)
      OR (NOT r.is_sirg_ref_placeholder AND NOT s.is_sdr_placeholder
          AND s.sdr_country = r.sirg_ref_country AND s.sdr_sirg_cd = r.sirg_ref_sirg_cd));

-- The final Import dataset — what the downstream application consumes.
-- Workbook rules are reproduced exactly as written (raw values), plus APPROVED proposals
-- formatted the workbook's way (DD-MM-YYYY text dates). Column names = the Import headers.
CREATE VIEW sirdb.v_import_final AS
SELECT 'WORKBOOK'::text                AS origin,
       r.batch_id                      AS origin_batch_id,
       r.source_row_no                 AS origin_row,
       r.region                        AS "Region",
       r.country                       AS "Country",
       r.shipment_type                 AS "B2B/B2C",
       r.effective_date_raw            AS "Effective Date (DD-MM-YYY)",
       r.expiry_date_raw               AS "Date of Expiry (DD-MM-YYY)",
       r.network_product_code_raw      AS "Network Product Code",
       r.value_basis                   AS "Declared Value/ Intristic Value",
       r.currency                      AS "Currency",
       r.min_value_raw                 AS "Min Value (>=)",
       r.max_value_raw                 AS "Max Value (<=)",
       r.min_weight_raw                AS "Shipt Weight (kg) (>=)",
       r.max_weight_raw                AS "Shipt Weight (kg) (<=)",
       r.other_logic                   AS "Other Logic",
       r.country_hold_code             AS "Country Hold Code",
       r.global_hold_code              AS "Global Hold Code",
       r.document_reference            AS "Document Reference",
       r.sirg_document_reference       AS "SIRG Document Reference"
FROM sirdb.import_rule r
WHERE r.batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
UNION ALL
SELECT 'PROPOSAL', p.validated_batch_id, p.proposal_id::int,
       p.region, p.country, p.shipment_type,
       to_char(p.effective_date, 'DD-MM-YYYY'), to_char(p.expiry_date, 'DD-MM-YYYY'),
       p.network_product_code, p.value_basis, p.currency,
       p.min_value::text, p.max_value::text, p.min_weight::text, p.max_weight::text,
       p.other_logic, p.country_hold_code, p.global_hold_code,
       p.document_reference,
       CASE WHEN p.sirg_cd IS NOT NULL THEN p.country || '|Import|' || p.sirg_cd END
FROM sirdb.rule_proposal p
WHERE p.status = 'APPROVED';
