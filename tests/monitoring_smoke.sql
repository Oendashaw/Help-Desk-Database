-- Read-only checks; detailed query execution is also covered by integration tests.
BEGIN READ ONLY;
DO $test$
DECLARE
    backlog bigint;
    grouped_backlog bigint;
BEGIN
    IF current_setting('track_counts') <> 'on' THEN
        RAISE EXCEPTION 'Enable track_counts for table/database monitoring';
    END IF;
    IF (SELECT count(*) FROM pg_stat_database WHERE datname = current_database()) <> 1 THEN
        RAISE EXCEPTION 'Missing database statistics';
    END IF;
    IF (SELECT count(*) FROM pg_stat_user_tables WHERE schemaname = 'public'
        AND relname IN ('staff', 'assets', 'tickets', 'ticket_updates')) <> 4 THEN
        RAISE EXCEPTION 'Missing help desk table statistics';
    END IF;
    PERFORM pid, state, wait_event_type, wait_event, query_start, xact_start,
            pg_blocking_pids(pid)
    FROM pg_stat_activity WHERE datname = current_database();
    PERFORM locktype, mode, granted FROM pg_locks;
    PERFORM idx_scan, idx_tup_read, idx_tup_fetch, pg_relation_size(indexrelid)
    FROM pg_stat_user_indexes WHERE schemaname = 'public';
    SELECT count(*) INTO backlog FROM public.tickets
    WHERE status IN ('open', 'in_progress');
    SELECT COALESCE(sum(n), 0) INTO grouped_backlog FROM (
        SELECT count(*) AS n FROM public.tickets
        WHERE status IN ('open', 'in_progress') GROUP BY assigned_to, status, priority
    ) AS groups;
    IF backlog <> grouped_backlog THEN
        RAISE EXCEPTION 'Backlog grouping loses tickets';
    END IF;
    RAISE NOTICE 'Built-in monitoring checks passed';
END;
$test$;
ROLLBACK;
