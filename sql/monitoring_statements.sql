-- Optional: requires pg_stat_statements preloaded and installed in public.
-- Setup/restart instructions are in README. This file never changes configuration.
-- Restricted users see only permitted query text; pg_read_all_stats expands access.
SELECT clock_timestamp() AS sampled_at, stats_reset, dealloc
FROM public.pg_stat_statements_info;

SELECT clock_timestamp() AS sampled_at, queryid, userid, calls,
       total_exec_time, mean_exec_time, min_exec_time, max_exec_time, rows,
       shared_blks_hit, shared_blks_read, temp_blks_read, temp_blks_written,
       stats_since, left(query, 500) AS query
FROM public.pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT 20;
