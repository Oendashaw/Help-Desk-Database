"""Compare canonical queries before/after transactional indexes using psql only."""

import argparse
import json
import re
import shutil
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_workloads(path=ROOT / 'sql/performance_queries.sql'):
    blocks = re.split(r'^-- workload: ([a-z_]+)\s*$', path.read_text(), flags=re.M)
    queries = {}
    for name, body in zip(blocks[1::2], blocks[2::2]):
        query = '\n'.join(line for line in body.splitlines()
                          if not line.lstrip().startswith('--')).strip()
        if not query.upper().startswith('SELECT ') or query.count(';') != 1 or not query.endswith(';'):
            raise ValueError(f'{name}: expected one SELECT ending in a semicolon')
        if name in queries:
            raise ValueError(f'Duplicate workload: {name}')
        queries[name] = query[:-1]
    if not queries:
        raise ValueError('No workloads found')
    return queries


def index_sql(path=ROOT / 'sql/02_indexes.sql'):
    # The benchmark owns the transaction. Permanent installation owns its own.
    return '\n'.join(line for line in path.read_text().splitlines()
                     if line.strip().upper() not in ('BEGIN;', 'COMMIT;'))


def build_sql(queries, runs):
    statements = ["""
BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
LOCK TABLE public.staff, public.assets, public.tickets, public.ticket_updates IN SHARE MODE;
DO $guard$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_index AS i
        JOIN pg_class AS t ON t.oid = i.indrelid
        JOIN pg_namespace AS n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname IN ('staff', 'assets', 'tickets', 'ticket_updates')
          AND NOT EXISTS (SELECT 1 FROM pg_constraint AS c WHERE c.conindid = i.indexrelid)
    ) THEN
        RAISE EXCEPTION 'Baseline requires constraint indexes only. Use a fresh disposable database; no indexes are dropped.';
    END IF;
END;
$guard$;
SELECT json_build_object('kind', 'environment',
    'server_version', current_setting('server_version'),
    'database', current_database(), 'sampled_at', clock_timestamp(),
    'shared_buffers', current_setting('shared_buffers'),
    'work_mem', current_setting('work_mem'),
    'random_page_cost', current_setting('random_page_cost'),
    'effective_cache_size', current_setting('effective_cache_size'),
    'jit', current_setting('jit'),
    'enable_seqscan', current_setting('enable_seqscan'),
    'staff', (SELECT count(*) FROM public.staff),
    'assets', (SELECT count(*) FROM public.assets),
    'tickets', (SELECT count(*) FROM public.tickets),
    'ticket_updates', (SELECT count(*) FROM public.ticket_updates));
"""]
    for stage in ('baseline', 'indexed'):
        if stage == 'indexed':
            statements.append(index_sql())
            statements.append("""SELECT json_build_object('kind', 'index_sizes', 'indexes',
                json_object_agg(indexrelname, pg_relation_size(indexrelid)))
                FROM pg_stat_user_indexes WHERE schemaname = 'public'
                  AND indexrelname IN ('idx_updates_ticket_created',
                    'idx_tickets_reporter_created', 'idx_tickets_active_agent_created');""")
        for name, query in queries.items():
            statements.append(f"""SELECT json_build_object('kind', 'result', 'stage', '{stage}',
                'workload', '{name}', 'rows', count(*),
                'fingerprint', md5(COALESCE(jsonb_agg(to_jsonb(q))::text, '[]')))
                FROM ({query}) AS q;""")
            # First EXPLAIN is a discarded warm-up; all plans are retained as evidence.
            for _ in range(runs + 1):
                statements.append(f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query};')
    statements.append('ROLLBACK;')
    return '\n'.join(statements)


def decode_stream(output):
    decoder = json.JSONDecoder()
    items = []
    position = 0
    while position < len(output):
        if output[position].isspace():
            position += 1
            continue
        item, position = decoder.raw_decode(output, position)
        items.append(item)
    return items


def summarize(items, queries, runs):
    cursor = 0
    environment = items[cursor]
    cursor += 1
    if environment.get('kind') != 'environment':
        raise ValueError('Missing benchmark environment')
    report = {'environment': environment, 'runs_per_workload': runs,
              'cache_policy': 'one warm-up per workload/stage; warm-cache comparison',
              'indexes_rolled_back': True, 'stages': {}}
    for stage in ('baseline', 'indexed'):
        if stage == 'indexed':
            sizes = items[cursor]
            cursor += 1
            if sizes.get('kind') != 'index_sizes' or not sizes.get('indexes'):
                raise ValueError('Missing index sizes')
            report['index_sizes_bytes'] = sizes['indexes']
        report['stages'][stage] = {}
        for name in queries:
            result = items[cursor]
            cursor += 1
            if (result.get('kind'), result.get('stage'), result.get('workload')) != ('result', stage, name):
                raise ValueError(f'Unexpected result for {stage}/{name}')
            if result['rows'] == 0:
                raise ValueError(f'{name} returned no rows; load the standard sample data')
            plans = items[cursor:cursor + runs + 1]
            cursor += runs + 1
            measured = [plan[0] for plan in plans[1:]]
            if len(measured) != runs:
                raise ValueError('Incomplete measurement output')
            report['stages'][stage][name] = {
                'rows': result['rows'], 'fingerprint': result['fingerprint'],
                'median_execution_ms': statistics.median(p['Execution Time'] for p in measured),
                'median_planning_ms': statistics.median(p['Planning Time'] for p in measured),
                'median_shared_hit_blocks': statistics.median(p['Plan'].get('Shared Hit Blocks', 0) for p in measured),
                'median_shared_read_blocks': statistics.median(p['Plan'].get('Shared Read Blocks', 0) for p in measured),
                'warmup_plan': plans[0], 'measured_plans': plans[1:],
            }
    if cursor != len(items):
        raise ValueError('Unexpected extra benchmark output')
    report['comparisons'] = {}
    for name in queries:
        before = report['stages']['baseline'][name]
        after = report['stages']['indexed'][name]
        if (before['rows'], before['fingerprint']) != (after['rows'], after['fingerprint']):
            raise ValueError(f'Query results changed after indexing: {name}')
        report['comparisons'][name] = {
            'results_equal': True,
            'speedup': before['median_execution_ms'] / after['median_execution_ms']
            if after['median_execution_ms'] else None,
        }
    return report


def markdown_report(report):
    lines = ['# Performance comparison', '',
             f"PostgreSQL {report['environment']['server_version']}; database `{report['environment']['database']}`.",
             f"{report['runs_per_workload']} measured executions after one warm-up per stage.",
             'Candidate indexes were rolled back; no existing indexes were removed.', '',
             '| Workload | Baseline ms | Indexed ms | Speedup | Results equal |',
             '|---|---:|---:|---:|---|']
    for name, comparison in report['comparisons'].items():
        before = report['stages']['baseline'][name]['median_execution_ms']
        after = report['stages']['indexed'][name]['median_execution_ms']
        speedup = comparison['speedup']
        ratio = f'{speedup:.2f}x' if speedup is not None else 'n/a'
        lines.append(f'| {name} | {before:.3f} | {after:.3f} | {ratio} | yes |')
    lines += ['', 'Index sizes (bytes):', '']
    lines += [f'- `{name}`: {size}' for name, size in report['index_sizes_bytes'].items()]
    lines += ['', 'Raw JSON contains plans, buffer counts, settings, and result fingerprints.',
              'These are local warm-cache measurements, not production latency guarantees.',
              'Index storage and write maintenance are costs; write overhead was not measured.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--psql', default=shutil.which('psql') or 'psql')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--username')
    parser.add_argument('--dbname', required=True, help='fresh sample database, before 02_indexes.sql')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True, help='new .json file; .md sibling is also created')
    args = parser.parse_args()
    if args.runs < 3 or args.runs > 100:
        parser.error('--runs must be between 3 and 100')
    if args.output.suffix.lower() != '.json':
        parser.error('--output must end in .json')
    summary = args.output.with_suffix('.md')
    if args.output.exists() or summary.exists():
        parser.error('Output already exists; select a new destination')
    queries = load_workloads()
    command = [args.psql, '-X', '-q', '-A', '-t', '-w', '-v', 'ON_ERROR_STOP=1']
    for flag, value in (('--host', args.host), ('--port', args.port),
                        ('--username', args.username), ('--dbname', args.dbname)):
        if value is not None:
            command += [flag, str(value)]
    try:
        process = subprocess.run(command, input=build_sql(queries, args.runs),
                                 capture_output=True, text=True, encoding='utf-8',
                                 timeout=300, check=False)
        if process.returncode:
            # Do not echo connection strings or server query text into saved reports.
            raise RuntimeError('psql failed; verify connection, empty baseline indexes, permissions, and sample data. No report saved.')
        report = summarize(decode_stream(process.stdout), queries, args.runs)
        report['generated_at_utc'] = datetime.now(timezone.utc).isoformat()
        report['queries'] = queries
        report['candidate_index_sql'] = index_sql()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(report, output, indent=2)
            output.write('\n')
        with summary.open('x', encoding='utf-8') as output:
            output.write(markdown_report(report))
    except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'Benchmark failed: {error}\n')
    print(f'Created {args.output} and {summary}; candidate indexes rolled back.')


if __name__ == '__main__':
    main()
