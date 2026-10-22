-- 0004 — Change history for reference data and rules.
--
-- Every INSERT / UPDATE / DELETE on the tables below is written to sirdb.change_log with the
-- old and new row. The actor comes from the session setting sirdb.actor
-- (SET LOCAL sirdb.actor = 'loader:alice'); it falls back to the database user.

CREATE TABLE sirdb.change_log (
    change_id   bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text        NOT NULL,
    table_name  text        NOT NULL,
    operation   text        NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    row_key     jsonb       NOT NULL,
    old_row     jsonb,
    new_row     jsonb
);
CREATE INDEX change_log_table ON sirdb.change_log (table_name, at);

CREATE FUNCTION sirdb.log_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    actor text := coalesce(nullif(current_setting('sirdb.actor', true), ''), current_user);
    keycols text[] := TG_ARGV;
    src jsonb := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    k jsonb := '{}'::jsonb;
    c text;
BEGIN
    FOREACH c IN ARRAY keycols LOOP
        k := k || jsonb_build_object(c, src -> c);
    END LOOP;
    -- UPDATEs that change nothing are not history.
    IF TG_OP = 'UPDATE' AND to_jsonb(OLD) = to_jsonb(NEW) THEN
        RETURN NEW;
    END IF;
    INSERT INTO sirdb.change_log (actor, table_name, operation, row_key, old_row, new_row)
    VALUES (actor, TG_TABLE_NAME, TG_OP, k,
            CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END);
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE TRIGGER audit_import_batch    AFTER INSERT OR UPDATE OR DELETE ON sirdb.import_batch
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('batch_id');
CREATE TRIGGER audit_technical_sir   AFTER INSERT OR UPDATE OR DELETE ON sirdb.technical_sir
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('batch_id', 'sir_technical_id');
CREATE TRIGGER audit_technical_sirg  AFTER INSERT OR UPDATE OR DELETE ON sirdb.technical_sirg
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('batch_id', 'source_row_no');
CREATE TRIGGER audit_logic           AFTER INSERT OR UPDATE OR DELETE ON sirdb.logic_expression
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('batch_id', 'source_row_no');
CREATE TRIGGER audit_list_item       AFTER INSERT OR UPDATE OR DELETE ON sirdb.reference_list_item
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('list_id', 'position');
CREATE TRIGGER audit_import_rule     AFTER INSERT OR UPDATE OR DELETE ON sirdb.import_rule
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('batch_id', 'source_row_no');
CREATE TRIGGER audit_sir_reference   AFTER INSERT OR UPDATE OR DELETE ON sirdb.sir_reference
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('batch_id', 'source_row_no');
CREATE TRIGGER audit_rule_proposal   AFTER INSERT OR UPDATE OR DELETE ON sirdb.rule_proposal
    FOR EACH ROW EXECUTE FUNCTION sirdb.log_change('proposal_id');

-- Source rows are evidence: once loaded they are never changed (a new workbook is a new batch).
CREATE FUNCTION sirdb.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'sirdb.% is append-only: load a new batch instead of changing source data', TG_TABLE_NAME;
END $$;
CREATE TRIGGER source_row_append_only  BEFORE UPDATE ON sirdb.source_row
    FOR EACH ROW WHEN (OLD.record IS DISTINCT FROM NEW.record) EXECUTE FUNCTION sirdb.forbid_change();
CREATE TRIGGER source_cell_append_only BEFORE UPDATE ON sirdb.source_cell
    FOR EACH ROW EXECUTE FUNCTION sirdb.forbid_change();
