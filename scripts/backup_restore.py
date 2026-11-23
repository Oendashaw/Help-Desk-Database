"""Back up the prepared help desk database and verify a fresh restore on the same cluster."""

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = (('staff', 'staff_id'), ('assets', 'asset_id'),
          ('tickets', 'ticket_id'), ('ticket_updates', 'update_id'))


def manifest_sql():
    # Table names and keys are internal constants; records are never interpolated into SQL.
    tables = []
    for table, key in TABLES:
        tables.append(f"""SELECT '{table}' AS name, jsonb_build_object(
            'rows', count(*),
            'fingerprint', md5(COALESCE(string_agg(to_jsonb(t)::text, E'\\n' ORDER BY {key}), '')),
            'samples', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.{key}) FROM
                (SELECT * FROM public.{table} ORDER BY {key} LIMIT 3) s)) AS details
            FROM public.{table} t""")
    return """BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SELECT jsonb_build_object(
    'superuser', (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),
    'server_major', current_setting('server_version_num')::integer / 10000,
    'tables', (SELECT jsonb_object_agg(name, details) FROM (
""" + '\nUNION ALL\n'.join(tables) + """
    ) AS table_data),
    'indexes', (SELECT jsonb_agg(indexdef ORDER BY tablename, indexname)
        FROM pg_indexes WHERE schemaname = 'public'
        AND tablename IN ('staff', 'assets', 'tickets', 'ticket_updates')),
    'sequences', (SELECT jsonb_object_agg(sequencename, last_value)
        FROM pg_sequences WHERE schemaname = 'public'),
    'views', (SELECT jsonb_object_agg(viewname, definition)
        FROM pg_views WHERE schemaname = 'reporting'),
    'ticket_summary', (SELECT jsonb_agg(to_jsonb(v) ORDER BY status, priority)
        FROM reporting.ticket_summary v),
    'asset_inventory', (SELECT jsonb_agg(to_jsonb(v) ORDER BY asset_type)
        FROM reporting.asset_inventory v),
    'privileges', (SELECT jsonb_agg(jsonb_build_object(
        'schema', n.nspname, 'name', c.relname, 'owner', pg_get_userbyid(c.relowner),
        'acl', (SELECT jsonb_agg(p::text ORDER BY p::text)
            FROM unnest(COALESCE(c.relacl, acldefault(
                CASE WHEN c.relkind = 'S' THEN 's'::"char" ELSE 'r'::"char" END,
                c.relowner))) p),
        'columns', (SELECT jsonb_object_agg(a.attname,
            (SELECT jsonb_agg(p::text ORDER BY p::text) FROM unnest(a.attacl) p))
            FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped))
        ORDER BY n.nspname, c.relname)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('public', 'reporting') AND c.relkind IN ('r', 'v', 'S'))
);
COMMIT;
"""


def run_tool(command, *, input_sql=None, archive=None):
    result = subprocess.run(
        command, input=input_sql, stdout=archive if archive is not None else subprocess.PIPE,
        stderr=subprocess.PIPE, text=archive is None,
        encoding='utf-8' if archive is None else None, timeout=300, check=False,
    )
    if result.returncode:
        # Saved reports must not include connection details or database error payloads.
        raise RuntimeError(f'{Path(command[0]).stem} failed with exit code {result.returncode}')
    return result.stdout


def inspect_database(psql, connection, database):
    result = run_tool([psql, *connection, '-X', '-q', '-A', '-t', '-w', '-v',
                       'ON_ERROR_STOP=1', '--dbname', database], input_sql=manifest_sql())
    return json.loads(result)


def verify_manifest(source, restored):
    if source != restored:
        changed = sorted(key for key in source.keys() | restored.keys()
                         if source.get(key) != restored.get(key))
        raise ValueError('Restore differs from source: ' + ', '.join(changed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbname', required=True, help='prepared source database')
    parser.add_argument('--restore-db', required=True, help='new database name on the same cluster')
    parser.add_argument('--backup', type=Path, required=True, help='new custom-format archive file')
    parser.add_argument('--output', type=Path, required=True, help='new JSON verification report')
    parser.add_argument('--pg-bin', type=Path, help='PostgreSQL 17 bin directory, otherwise use PATH')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--username')
    args = parser.parse_args()
    for name in (args.dbname, args.restore_db):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name):
            parser.error('Database names must be lowercase ASCII identifiers, not connection strings')
    if args.dbname == args.restore_db or args.restore_db in ('postgres', 'template0', 'template1'):
        parser.error('Use a separate, new restore database')
    if args.output.suffix.lower() != '.json':
        parser.error('--output must end in .json')
    if args.backup.resolve() == args.output.resolve():
        parser.error('Backup and report paths must differ')
    if args.backup.exists() or args.output.exists():
        parser.error('Backup or report already exists; select new paths')

    tools = {}
    for name in ('psql', 'pg_dump', 'createdb', 'pg_restore'):
        executable = shutil.which(name, path=str(args.pg_bin)) if args.pg_bin else shutil.which(name)
        if executable is None:
            parser.error(f'{name} not found; supply --pg-bin or configure PATH')
        tools[name] = executable
    connection = []
    for flag, value in (('--host', args.host), ('--port', args.port), ('--username', args.username)):
        if value is not None:
            connection.extend((flag, str(value)))
    report = {'success': False, 'source_database': args.dbname,
              'restore_database': args.restore_db, 'backup_file': args.backup.name,
              'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'restore_database_created': False, 'stage': 'inspect source'}
    exit_code = 0
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as output:
            try:
                # shortcut: source must stay quiet; export a shared snapshot if concurrent-write support is needed.
                source = inspect_database(tools['psql'], connection, args.dbname)
                if not source['superuser'] or source['server_major'] != 17:
                    raise ValueError('Use a PostgreSQL 17 superuser for owner/grant restoration and permission tests')
                report['source'] = source
                report['stage'] = 'backup'
                args.backup.parent.mkdir(parents=True, exist_ok=True)
                with args.backup.open('xb') as archive:
                    run_tool([tools['pg_dump'], *connection, '-w', '--format=custom',
                              '--dbname', args.dbname], archive=archive)
                report['backup_bytes'] = args.backup.stat().st_size
                report['stage'] = 'create restore database'
                report['restore_database_created'] = None
                run_tool([tools['createdb'], *connection, '-w', '--template=template0', args.restore_db])
                report['restore_database_created'] = True
                report['stage'] = 'restore'
                run_tool([tools['pg_restore'], *connection, '-w', '--exit-on-error',
                          '--single-transaction', '--dbname', args.restore_db, str(args.backup)])
                report['stage'] = 'compare restore'
                restored = inspect_database(tools['psql'], connection, args.restore_db)
                report['restored'] = restored
                verify_manifest(source, restored)
                report['stage'] = 'restored database checks'
                report['checks_passed'] = []
                for check in ('schema_smoke.sql', 'index_smoke.sql', 'permissions_smoke.sql'):
                    run_tool([tools['psql'], *connection, '-X', '-w', '-v', 'ON_ERROR_STOP=1',
                              '--dbname', args.restore_db, '-f', str(ROOT / 'tests' / check)])
                    report['checks_passed'].append(check)
                report['success'] = True
                report['stage'] = 'complete'
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                report['error'] = str(error) or 'Interrupted'
                exit_code = 1
            finally:
                report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
                json.dump(report, output, indent=2)
                output.write('\n')
    except OSError as error:
        parser.exit(1, f'Could not write recovery artifacts: {error}\n')
    if exit_code:
        parser.exit(exit_code, f"Recovery failed at {report['stage']}: {report['error']}. "
                    'Created artifacts are retained; use new paths and a new restore name to retry.\n')
    print(f'Backup and restore verified. Report saved to {args.output}.')


if __name__ == '__main__':
    main()
