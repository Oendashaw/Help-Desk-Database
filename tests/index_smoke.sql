-- Plain SQL; run after 02_indexes.sql on the populated sample database.
BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL statement_timeout = '30s';
DO $test$
DECLARE
    expected record;
    actual record;
BEGIN
    FOR expected IN
        SELECT * FROM (VALUES
            ('idx_updates_ticket_created', 'ticket_updates', 'ticket_id', 'created_at', 'update_id', false, false),
            ('idx_tickets_reporter_created', 'tickets', 'reported_by', 'created_at', 'ticket_id', false, true),
            ('idx_tickets_active_agent_created', 'tickets', 'assigned_to', 'created_at', 'ticket_id', true, true)
        ) AS e(index_name, table_name, key1, key2, key3, partial, descending)
    LOOP
        SELECT t.relname AS table_name, am.amname, i.indisvalid, i.indisready,
               i.indisunique, i.indnkeyatts, i.indnatts,
               pg_get_indexdef(i.indexrelid, 1, true) AS key1,
               pg_get_indexdef(i.indexrelid, 2, true) AS key2,
               pg_get_indexdef(i.indexrelid, 3, true) AS key3,
               pg_index_column_has_property(i.indexrelid, 1, 'asc') AS key1_ascending,
               pg_index_column_has_property(i.indexrelid, 2, 'desc') AS key2_descending,
               pg_index_column_has_property(i.indexrelid, 3, 'desc') AS key3_descending,
               pg_get_expr(i.indpred, i.indrelid) AS predicate
        INTO actual
        FROM pg_index AS i
        JOIN pg_class AS ix ON ix.oid = i.indexrelid
        JOIN pg_class AS t ON t.oid = i.indrelid
        JOIN pg_am AS am ON am.oid = ix.relam
        WHERE i.indexrelid = to_regclass('public.' || expected.index_name);
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Missing index: %', expected.index_name;
        END IF;
        IF actual.table_name <> expected.table_name OR actual.amname <> 'btree'
           OR NOT actual.indisvalid OR NOT actual.indisready OR actual.indisunique
           OR actual.indnkeyatts <> 3 OR actual.indnatts <> 3
           OR actual.key1 <> expected.key1 OR actual.key2 <> expected.key2
           OR actual.key3 <> expected.key3
           OR actual.key1_ascending IS DISTINCT FROM true
           OR actual.key2_descending IS DISTINCT FROM expected.descending
           OR actual.key3_descending IS DISTINCT FROM expected.descending THEN
            RAISE EXCEPTION 'Incorrect definition for %', expected.index_name;
        END IF;
        IF expected.partial THEN
            IF actual.predicate IS DISTINCT FROM
                '(status = ANY (ARRAY[''open''::text, ''in_progress''::text]))' THEN
                RAISE EXCEPTION 'Incorrect active-status predicate: %', actual.predicate;
            END IF;
        ELSIF actual.predicate IS NOT NULL THEN
            RAISE EXCEPTION 'Unexpected partial index: %', expected.index_name;
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT FROM public.tickets WHERE reported_by = 42)
       OR NOT EXISTS (SELECT FROM public.tickets WHERE assigned_to = 7 AND status IN ('open', 'in_progress'))
       OR NOT EXISTS (SELECT FROM public.ticket_updates WHERE ticket_id = 25000) THEN
        RAISE EXCEPTION 'Load the standard dataset before testing query equivalence';
    END IF;
END;
$test$;

-- Compare deterministic query results with index paths disabled and enabled.
-- Planner settings are local to this test, never part of the benchmark.
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
CREATE TEMP TABLE baseline_updates ON COMMIT DROP AS
SELECT update_id, author_id, update_text, created_at FROM public.ticket_updates
WHERE ticket_id = 25000 ORDER BY created_at, update_id;
CREATE TEMP TABLE baseline_reporter ON COMMIT DROP AS
SELECT ticket_id, subject, status, priority, created_at FROM public.tickets
WHERE reported_by = 42 ORDER BY created_at DESC, ticket_id DESC LIMIT 50;
CREATE TEMP TABLE baseline_agent ON COMMIT DROP AS
SELECT ticket_id, subject, status, priority, created_at FROM public.tickets
WHERE assigned_to = 7 AND status IN ('open', 'in_progress')
ORDER BY created_at DESC, ticket_id DESC LIMIT 50;

SET LOCAL enable_indexscan = on;
SET LOCAL enable_indexonlyscan = on;
SET LOCAL enable_bitmapscan = on;
DO $test$
BEGIN
    IF EXISTS (
        WITH indexed AS (
            SELECT update_id, author_id, update_text, created_at FROM public.ticket_updates
            WHERE ticket_id = 25000 ORDER BY created_at, update_id
        )
        (SELECT * FROM baseline_updates EXCEPT ALL SELECT * FROM indexed)
        UNION ALL
        (SELECT * FROM indexed EXCEPT ALL SELECT * FROM baseline_updates)
    ) THEN RAISE EXCEPTION 'Ticket conversation results differ'; END IF;
    IF EXISTS (
        WITH indexed AS (
            SELECT ticket_id, subject, status, priority, created_at FROM public.tickets
            WHERE reported_by = 42 ORDER BY created_at DESC, ticket_id DESC LIMIT 50
        )
        (SELECT * FROM baseline_reporter EXCEPT ALL SELECT * FROM indexed)
        UNION ALL
        (SELECT * FROM indexed EXCEPT ALL SELECT * FROM baseline_reporter)
    ) THEN RAISE EXCEPTION 'Reporter history results differ'; END IF;
    IF EXISTS (
        WITH indexed AS (
            SELECT ticket_id, subject, status, priority, created_at FROM public.tickets
            WHERE assigned_to = 7 AND status IN ('open', 'in_progress')
            ORDER BY created_at DESC, ticket_id DESC LIMIT 50
        )
        (SELECT * FROM baseline_agent EXCEPT ALL SELECT * FROM indexed)
        UNION ALL
        (SELECT * FROM indexed EXCEPT ALL SELECT * FROM baseline_agent)
    ) THEN RAISE EXCEPTION 'Agent queue results differ'; END IF;
    RAISE NOTICE 'Index definitions and query equivalence checks passed';
END;
$test$;
ROLLBACK;
