# SQL examples

All examples use the **current batch**. Replace the sub-select with a number to query an older one.

```sql
-- The current batch
SELECT batch_id, source_filename, file_sha256, loaded_at FROM sirdb.import_batch WHERE is_current;

-- 1. Resolve an Import SIRG key: country + processing type + SIRG code (0 / 1 / many rows)
SELECT source_row_no, sirg_technical_id, sirg_nm, cmpt_nm, sir_technical_id
FROM sirdb.technical_sirg
WHERE batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
  AND dhl_ctry_cd = 'DE' AND processing_type = 'IMP_CLR' AND sirg_cd = 'POA';
--  → 613 | dfb77196… | Power of Attorney | DEPOA | b5a141ed…

-- 2. Check that the SIR id / component pair exists in Technical SIR
SELECT s.cmpt_nm = g.cmpt_nm AS pair_ok, s.nm, s.dsc
FROM sirdb.technical_sirg g
JOIN sirdb.technical_sir s USING (batch_id, sir_technical_id)
WHERE g.batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
  AND g.dhl_ctry_cd = 'DE' AND g.processing_type = 'IMP_CLR' AND g.sirg_cd = 'POA';

-- 3. SIR Reference lines and attributes for a country + SIRG code (one-to-many)
SELECT r.source_row_no, r.cmpt_nm, r.sir_technical_id, r.waived_if_whitelisted_raw, r.waived_to_validate_raw,
       r.check_if_service_code, a.position, a.attribute_id, a.col_09_entry
FROM sirdb.sir_reference r
LEFT JOIN sirdb.sir_reference_attribute a USING (batch_id, source_row_no)
WHERE r.batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
  AND NOT r.is_sdr_placeholder AND r.sdr_country = 'MX' AND r.sdr_sirg_cd = 'IRID'
ORDER BY r.source_row_no, a.position;
--  → rows 67–70: TAX ID, CURP, Foreigner TAX ID, Foreigner National ID

-- 4. Resolution status of every Import rule
SELECT source_row_no, country, sirg_document_reference, sirg_status, cmpt_nm, sir_pair_in_catalog
FROM sirdb.v_import_rule_sirg
WHERE batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
ORDER BY source_row_no;

-- 5. Which SIR Reference lines belong to which Import rule, and by which join
SELECT import_row, sir_reference_row, join_style, cmpt_nm, attribute_id_raw
FROM sirdb.v_import_rule_sir_reference
WHERE batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
ORDER BY import_row, sir_reference_row;

-- 6. SIR Reference lines with no Import rule (orphans, Q-11)
SELECT s.source_row_no, s.document_reference, s.sir_document_reference
FROM sirdb.sir_reference s
WHERE s.batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
  AND NOT EXISTS (SELECT 1 FROM sirdb.v_import_rule_sir_reference v
                  WHERE v.batch_id = s.batch_id AND v.sir_reference_row = s.source_row_no);

-- 7. Exceptions: placeholders, date anomalies, unresolved links — straight from the findings
SELECT severity, code, sheet_name, row_no, column_name, value_text, message
FROM sirdb.load_issue
WHERE batch_id = (SELECT batch_id FROM sirdb.v_current_batch) AND severity <> 'info'
ORDER BY sheet_name, row_no;

-- 8. A source cell exactly as it was (value and formula)
SELECT value_text, value_type, formula FROM sirdb.source_cell
WHERE batch_id = (SELECT batch_id FROM sirdb.v_current_batch)
  AND sheet_name = 'SIR Reference' AND row_no = 6 AND col_index = 1;
--  → NO|Import|PFX|CIDM | str | =IF(Import!P4<>0,Import!P4,"")

-- 9. The final Import dataset (what the downstream application reads)
SELECT "Region", "Country", "B2B/B2C", "Effective Date (DD-MM-YYY)", "Date of Expiry (DD-MM-YYY)",
       "Network Product Code", "Declared Value/ Intristic Value", "Currency", "Min Value (>=)", "Max Value (<=)",
       "Shipt Weight (kg) (>=)", "Shipt Weight (kg) (<=)", "Other Logic", "Country Hold Code", "Global Hold Code",
       "Document Reference", "SIRG Document Reference"
FROM sirdb.v_import_final ORDER BY origin DESC, origin_row;

-- 10. Compare two workbook versions: SIRG mappings added or removed
SELECT 'added' AS change, n.dhl_ctry_cd, n.sirg_cd, n.cmpt_nm FROM sirdb.technical_sirg n
WHERE n.batch_id = :new AND NOT EXISTS (SELECT 1 FROM sirdb.technical_sirg o WHERE o.batch_id = :old
      AND (o.dhl_ctry_cd, o.processing_type, o.sirg_cd, o.sir_technical_id)
        = (n.dhl_ctry_cd, n.processing_type, n.sirg_cd, n.sir_technical_id))
UNION ALL
SELECT 'removed', o.dhl_ctry_cd, o.sirg_cd, o.cmpt_nm FROM sirdb.technical_sirg o
WHERE o.batch_id = :old AND NOT EXISTS (SELECT 1 FROM sirdb.technical_sirg n WHERE n.batch_id = :new
      AND (n.dhl_ctry_cd, n.processing_type, n.sirg_cd, n.sir_technical_id)
        = (o.dhl_ctry_cd, o.processing_type, o.sirg_cd, o.sir_technical_id));

-- 11. Who changed what
SELECT at, actor, table_name, operation, row_key FROM sirdb.change_log ORDER BY change_id DESC LIMIT 50;
```
