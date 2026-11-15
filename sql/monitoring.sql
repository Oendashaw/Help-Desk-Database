-- Read-only, PostgreSQL 17; run as separate autocommit statements for fresh stats.
-- Cross-user query details require pg_read_all_stats (coordinate with roles owner).
-- Sample counters twice in separate transactions; compare deltas, not just totals.

SELECT clock_timestamp() AS sampled_at, current_database() AS database_name,
       current_setting('server_version') AS server_version,
       pg_postmaster_start_time() AS server_started_at,
       current_setting('track_counts') AS track_counts,
       current_setting('track_io_timing') AS track_io_timing;

-- Current activity; age applies only to active queries, xact_age to transactions.
SELECT clock_timestamp() AS sampled_at, pid, usename, application_name, state,
       CASE WHEN state = 'active' THEN clock_timestamp() - query_start END AS active_query_age,
       clock_timestamp() - xact_start AS transaction_age,
       wait_event_type, wait_event, left(query, 300) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
ORDER BY xact_start NULLS LAST, pid;

-- Blocking edges, including waits that are difficult to infer from pg_locks alone.
SELECT clock_timestamp() AS sampled_at, a.pid AS blocked_pid,
       b.pid AS blocking_pid, a.wait_event_type, a.wait_event,
       clock_timestamp() - a.query_start AS waiting_query_age,
       left(a.query, 200) AS blocked_query, left(b.query, 200) AS blocking_query
FROM pg_stat_activity AS a
CROSS JOIN LATERAL unnest(pg_blocking_pids(a.pid)) AS p(blocking_pid)
LEFT JOIN pg_stat_activity AS b ON b.pid = p.blocking_pid
WHERE a.datname = current_database();

SELECT clock_timestamp() AS sampled_at, l.pid, l.locktype, l.mode, l.granted,
       l.relation::regclass AS relation, l.transactionid
FROM pg_locks AS l
JOIN pg_stat_activity AS a ON a.pid = l.pid
WHERE a.datname = current_database()
ORDER BY l.granted, l.pid, l.locktype;

SELECT clock_timestamp() AS sampled_at, datname, numbackends, xact_commit,
       xact_rollback, deadlocks, temp_files, temp_bytes, blks_hit, blks_read,
       round(100.0 * blks_hit / NULLIF(blks_hit::numeric + blks_read, 0), 2)
           AS shared_buffer_hit_pct,
       stats_reset
FROM pg_stat_database WHERE datname = current_database();

-- n_live_tup/n_dead_tup are estimates. Dead rows alone do not prove bloat.
SELECT clock_timestamp() AS sampled_at, relname, n_live_tup, n_dead_tup,
       seq_scan, seq_tup_read, idx_scan, n_tup_ins, n_tup_upd, n_tup_del,
       last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
       pg_table_size(relid) AS table_bytes,
       pg_indexes_size(relid) AS indexes_bytes,
       pg_total_relation_size(relid) AS total_bytes
FROM pg_stat_user_tables
WHERE schemaname = 'public'
  AND relname IN ('staff', 'assets', 'tickets', 'ticket_updates')
ORDER BY relname;

SELECT clock_timestamp() AS sampled_at, s.relname, s.indexrelname,
       s.idx_scan, s.idx_tup_read, s.idx_tup_fetch,
       pg_relation_size(s.indexrelid) AS index_bytes,
       i.indisvalid, i.indisready, pg_get_indexdef(s.indexrelid) AS definition
FROM pg_stat_user_indexes AS s
JOIN pg_index AS i ON i.indexrelid = s.indexrelid
WHERE s.schemaname = 'public'
  AND s.relname IN ('staff', 'assets', 'tickets', 'ticket_updates')
ORDER BY s.relname, s.indexrelname;

-- Operational backlog, distinct from server health. No resolution timestamps exist.
SELECT clock_timestamp() AS sampled_at, assigned_to, status, priority,
       count(*) AS ticket_count, min(created_at) AS oldest_created_at,
       clock_timestamp() - min(created_at) AS oldest_ticket_age
FROM public.tickets
WHERE status IN ('open', 'in_progress')
GROUP BY assigned_to, status, priority
ORDER BY assigned_to NULLS FIRST, status,
         CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                       WHEN 'medium' THEN 3 ELSE 4 END;
