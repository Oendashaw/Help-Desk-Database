# Performance and monitoring contribution

## Scope and design

The original schema, generator, existing tests, and recorded teammate results are preserved.
This contribution adds three workloads, three B-tree indexes, a transactional benchmark,
read-only monitoring, a controlled blocking demonstration, and opt-in integration tests.
It does not implement team-owned roles or backup/restore modules.

| Workload | Reason for index | Candidate index |
|---|---|---|
| Ticket conversation | Find a ticket's notes without scanning every update; return stable chronological order | `ticket_updates (ticket_id, created_at, update_id)` |
| Reporter history | Equality on reporter followed by newest-first retrieval and LIMIT | `tickets (reported_by, created_at DESC, ticket_id DESC)` |
| Active agent queue | Equality on agent, newest-first retrieval, omit resolved/closed rows | Partial `tickets (assigned_to, created_at DESC, ticket_id DESC)` for open/in-progress |

The schema already creates six indexes through four primary keys and two unique
constraints. No duplicate indexes are added for these keys. The update and reporter
indexes also support their leading foreign-key columns. The partial agent index does
not cover all referencing rows, so it is not a complete foreign-key maintenance index.
Other foreign-key indexes should be justified by future workload measurements.

The active queue is newest-first. For business priority ordering, use a CASE expression
mapping urgent=1, high=2, medium=3, low=4; alphabetical text order is unsuitable.
The current index is not designed to eliminate that expression's sort.

## Benchmark method

1. Use a disposable database with the original schema and standard generated data.
2. Run the benchmark **before** installing `02_indexes.sql`.
3. The benchmark opens one repeatable-read transaction and takes SHARE table locks.
   This prevents writes during the comparison. Run it during a quiet demonstration;
   the benchmark is not a production load-testing tool.
4. It refuses any non-constraint index on the four tables, rather than dropping or
   changing existing indexes. It requires owner-level permission to create indexes.
5. For each query/stage, compute a result fingerprint, warm up once, then retain at
   least three measured `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans; default five.
6. Create candidate indexes within the transaction, repeat the exact workloads,
   compare result counts/fingerprints, and roll back the candidate indexes.
7. Save environment/settings, dataset counts, plans, median execution/planning times,
   median root shared-buffer hits/reads, index sizes, and a Markdown comparison.
   Repeated output paths are refused. No password or connection command is saved.
8. Install the separate index script only after retaining the baseline comparison.

All fingerprint checks must match. A zero-row workload is rejected because an empty
query is not a meaningful demonstration. Deterministic ORDER BY clauses include unique
ID tie breakers. Queries use known sample IDs, avoiding date windows that become empty
as the fixed January–October 2026 dataset ages.

The generator already runs ANALYZE. If you substantially change data, run ANALYZE on
the affected tables before benchmarking. Do not disable sequential scans or change
planner settings between stages to force a favorable result. A sequential scan can
be correct for broad queries or small tables.

These measurements describe warm-cache server execution, not cold-disk latency,
network transmission, client rendering, concurrent throughput, or write overhead.
Index building also warms cache; report this limitation. Use several independent
runs with new output names for stronger evidence. No universal timing threshold is
part of the tests. An index is not proven beneficial until actual plans and timings
are collected. Index storage and insert/update maintenance are real costs.

## Monitoring and interpretation

Run `sql/monitoring.sql` in autocommit mode. The queries include sampled timestamps
and cover activity, blocking edges, lock details, database counters, table health,
index usage/size, and active-ticket backlog. Run snapshots in separate transactions;
a long-lived transaction can present cached statistics.

| Observation | Investigation |
|---|---|
| Long active query or idle transaction | Inspect query, transaction age, and wait event before taking action |
| Blocking edge | Identify both PIDs and the holding transaction; use the controlled demo |
| Rising dead-row estimates and old analyze/vacuum timestamps | Check maintenance activity and table churn; estimates do not establish bloat |
| High sequential row reads | Correlate with query plans; full scans can be appropriate |
| Rising temp bytes/files | Inspect sort/hash plans and workload before changing work_mem |
| Few scans on a new index | Observe a representative interval before deciding it is unused |
| Low buffer hit percentage | Compare workload and physical I/O; PostgreSQL misses may still hit the OS cache |

Cumulative counters need interval deltas and reset/start timestamps. The built-in
script reports `pg_stat_database.stats_reset`; optional statement statistics have
separate reset information. It never resets global statistics, cancels sessions,
changes server settings, or runs maintenance automatically. Backlog counts and ticket
ages are business metrics; they are not server-health metrics. Resolution duration
cannot be measured without resolution timestamps or structured status history.

Normal users see their own session details; ask the roles owner about a dedicated
monitoring login with `pg_read_all_stats`. Do not use administrator credentials for
routine monitoring. Local owner/superuser testing does not validate restricted-role
visibility. The README's optional extension setup requires administrator involvement.

## pgAdmin manual acceptance checklist

Use a disposable `helpdesk_perf` database containing the standard sample data.

- Run `sql/performance_queries.sql` before indexing. For each SELECT, use pgAdmin
  Explain Analyze or prefix `EXPLAIN (ANALYZE, BUFFERS)` and retain the plan.
- Run the automated benchmark from a terminal before permanent index installation;
  JSON and Markdown reports provide the repeated comparison.
- Run `sql/02_indexes.sql` once. In the object browser, refresh the tables' Indexes
  nodes. Check all three definitions and the agent index's predicate.
- Repeat the three Explain Analyze queries. Look for index access and avoided sorts;
  compare rows scanned, buffers, and measured execution times. Do not require one
  exact planner node or claim a speedup based only on estimated cost.
- Run `tests/index_smoke.sql` and `tests/monitoring_smoke.sql` in Query Tool. Both
  must print their success notices. Test transactions end with ROLLBACK.
- Existing `schema_smoke.sql` and `data_smoke.sql` start with the psql-only
  `\set ON_ERROR_STOP on`; run those via psql/the integration suite. If using
  pgAdmin, select only the SQL below that first line.
- Run `sql/monitoring.sql` in autocommit mode and export its result grids. Execute a
  workload, wait briefly for statistics publication, then take a new snapshot.
- Follow the individual sections of `sql/blocking_demo.sql` in three separate Query
  Tools. Confirm session B is blocked by A in the third session's monitoring output.
  Roll back A, then B. If B times out, issue ROLLBACK to clear its failed transaction.
  Never execute the whole blocking demo file at once.
- If enabled, run a workload, then `sql/monitoring_statements.sql`; verify calls and
  execution/buffer counters. Capture a second sample and identify counter changes.
- Repeat monitoring with the intended monitoring login. Verify cross-user query
  visibility matches that role's grants; coordinate any changes with the roles owner.
- Confirm no demonstration transaction remains idle/open.

## Validation status in this workspace

The Python suite is executable without a database. Live database tests require a
prepared PostgreSQL database. During implementation the sandbox rejected PostgreSQL
17.11 shared-memory allocation while initializing an isolated cluster, and the local
5432 readiness probe returned no response. See `results/database_setup.txt` and
`results/validation.txt`. No timing results or successful SQL execution are claimed.
The generated benchmark reports will be created only after a successful live run.

## References

- [PostgreSQL 17: Multicolumn indexes](https://www.postgresql.org/docs/17/indexes-multicolumn.html)
- [PostgreSQL 17: Partial indexes](https://www.postgresql.org/docs/17/indexes-partial.html)
- [PostgreSQL 17: EXPLAIN](https://www.postgresql.org/docs/17/sql-explain.html)
- [PostgreSQL 17: Monitoring statistics](https://www.postgresql.org/docs/17/monitoring-stats.html)
- [PostgreSQL 17: pg_stat_statements](https://www.postgresql.org/docs/17/pgstatstatements.html)
