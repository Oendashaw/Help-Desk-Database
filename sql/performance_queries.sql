-- Canonical benchmark workloads. Plain SQL: run in psql or pgAdmin.
-- Fixed IDs exist in the standard dataset. Tie breakers make LIMIT deterministic.
-- To inspect plans, prefix each SELECT with EXPLAIN (ANALYZE, BUFFERS).
-- benchmark.py reads the named blocks below; keep one SELECT per block.

-- workload: ticket_conversation
SELECT update_id, author_id, update_text, created_at
FROM public.ticket_updates
WHERE ticket_id = 25000
ORDER BY created_at, update_id;

-- workload: reporter_history
SELECT ticket_id, subject, status, priority, created_at
FROM public.tickets
WHERE reported_by = 42
ORDER BY created_at DESC, ticket_id DESC
LIMIT 50;

-- workload: active_agent_queue
SELECT ticket_id, subject, status, priority, created_at
FROM public.tickets
WHERE assigned_to = 7
  AND status IN ('open', 'in_progress')
ORDER BY created_at DESC, ticket_id DESC
LIMIT 50;
