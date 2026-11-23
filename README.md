# PostgreSQL Help Desk Database Administration

CSCE 4355 team project by Oli Endashaw and Moses Ojo.

This project uses a PostgreSQL database to track help desk tickets, staff, and company devices with synthetic data. The planned demonstrations cover database permissions, query performance, monitoring, and backup and restore.

## Prerequisites

- PostgreSQL 17 with the `psql`, `createdb`, `pg_dump`, and `pg_restore` command-line tools
- Python 3 for sample data generation and verification scripts

## Database design

- `staff` stores names, unique email addresses, and departments.
- `assets` stores unique device tags, device types, and optional staff assignments.
- `tickets` links a required reporter to an optional assigned staff member and device.
- `ticket_updates` links each note to its ticket and author.

Tickets default to status `open` and priority `medium`. Statuses are `open`, `in_progress`, `resolved`, and `closed`. Priorities are `low`, `medium`, `high`, and `urgent`. Foreign keys prevent deleting records that other records still reference.

## Create the database

Start PostgreSQL 17 and run these commands from the repository root in PowerShell. Use your PostgreSQL administrator account if its name differs from `postgres`. The password prompts keep credentials out of the commands.

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\createdb.exe' -h localhost -U postgres -W helpdesk
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -h localhost -U postgres -W -d helpdesk -f sql/01_schema.sql
```

The schema script creates all four tables in one transaction. Run it once in a new, empty database. An existing table causes the transaction to fail without replacing existing data.

## Verify the schema

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -h localhost -U postgres -W -d helpdesk -f tests/schema_smoke.sql
```

The check creates a staff member, a device, tickets, and an update. It verifies their relationships and defaults, and confirms that invalid values, missing references, duplicate emails, and deletion of referenced staff are rejected. Success prints `NOTICE: Schema checks passed`.

Test rows are rolled back. Identity sequences can still advance, so gaps in generated IDs are expected.

## Generate and load sample data

Run from the repository root after creating the schema in an empty database.

```powershell
python scripts/generate_data.py
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk -f sample_data/helpdesk_data.sql
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk -f tests/data_smoke.sql
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk -f tests/schema_smoke.sql
```

The standard-library generator uses seed `4355` and fixed dates from January through October 2026. It creates 200 synthetic staff members, 1,000 assets, 50,000 tickets, and one to three updates per ticket. The first 20 staff members represent help desk agents. Email addresses use the reserved `example.invalid` domain.

The generated file is excluded from Git. Existing output files are preserved. To generate another identical copy, pass a new destination, such as `python scripts/generate_data.py sample_data/second_copy.sql`.

Loading requires all four tables to be empty. The import locks them against concurrent writes, loads all records in one transaction, advances identity sequences, and updates planner statistics. A repeat import fails without replacing existing records.

## Python checks

```powershell
python -m compileall -q scripts
python -m unittest discover -s tests -p 'test_*.py' -v
```

These checks verify repeatable output and preservation of existing output files. The SQL checks above verify the loaded records and schema.

## Repository structure

- `sql/01_schema.sql` creates the four tables and their constraints.
- `scripts/generate_data.py` creates the reproducible import file.
- `tests/schema_smoke.sql` verifies the schema with synthetic records.
- `tests/data_smoke.sql` checks the generated dataset after import.
- `tests/test_generate_data.py` checks generator repeatability and file handling.
- `results/data_generation.txt` records disposable PostgreSQL import and rollback checks.
- `sql/03_roles.sql` creates the three cluster-wide permission groups.
- `sql/04_permissions.sql` installs per-database grants and aggregate reporting views.
- `tests/permissions_smoke.sql` checks allowed/denied operations and GRANT/REVOKE.
- `results/security_validation.txt` records live role and login verification.
- `scripts/backup_restore.py` backs up and verifies a separate restored database.
- `tests/test_backup_restore.py` checks recovery safeguards and failure handling.
- `results/recovery_run_01.json` records the verified source and restored manifests.
- `results/recovery_validation.txt` records live recovery and regression checks.

Performance, indexing, monitoring, permissions, and backup/recovery scripts are described below.

## Roles and permissions

Use the database owner/administrator for installation. Run role creation once per
PostgreSQL cluster, then install permissions once in each dedicated help desk database.
The scripts are transactional and fail on existing role/schema names rather than
altering unrelated objects. Reuse the existing roles for another database by running
only `04_permissions.sql` there. Install roles and permissions before running the live Python suite.

Run the permission smoke test and full live integration suite as a PostgreSQL
superuser, such as `postgres`. Database ownership or `CREATEROLE` alone does not
permit the tests' `SET ROLE` operations. Application logins keep their limited roles.

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk -f sql/03_roles.sql
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk -f sql/04_permissions.sql
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk -f tests/permissions_smoke.sql
```

| Role | Access |
|---|---|
| `helpdesk_agent` | Read staff IDs/names/departments, assets, tickets, and updates. Create tickets and append updates. Edit ticket assignment, status, and priority. |
| `asset_reader` | Read device records only. |
| `report_reader` | Read `reporting.ticket_summary` and `reporting.asset_inventory`, which contain aggregate counts. |

Agents cannot read staff email, edit staff/devices, rewrite ticket updates, delete
records, or create public tables. Access applies across the help desk dataset;
per-agent row filtering is outside this module. Report readers have no base-table
access. The aggregate views deliberately use their owner's underlying table access.
Installation removes PUBLIC table/sequence grants and PUBLIC's ability to create
objects in the `public` schema, so use a dedicated project database. Existing grants
to other named roles are outside this script's scope.

These three roles are NOLOGIN permission groups with no administrative attributes.
To add a local demonstration login, run the following in an administrator's psql
session, then set its password at the interactive prompt. Repeat with distinct login
names for the other two groups. Credentials must stay outside the repository.

```sql
CREATE ROLE demo_agent LOGIN;
GRANT helpdesk_agent TO demo_agent;
\password demo_agent
```

The permission smoke test uses `SET LOCAL ROLE`, performs allowed actions, checks
denied actions for all three groups, compares reporting totals, and demonstrates
GRANT followed by REVOKE. Rows and temporary grants are rolled back; identity
sequences may advance. Run it after loading the sample data. For `helpdesk_perf`,
apply `04_permissions.sql` to that database before enabling live integration tests.
Full server-wide monitoring visibility requires a separately authorized monitoring
login; these application roles do not receive `pg_read_all_stats`.

## Backup and recovery

Use a PostgreSQL 17 superuser and a prepared database containing the schema, sample
data, indexes, and permissions. Configure a password file or `PGPASSFILE` as described
below; utilities use `-w` and fail instead of prompting. Run from the repository root.
Choose unused restore database, backup, and report names for each run.

```powershell
python scripts/backup_restore.py --dbname helpdesk --restore-db helpdesk_restore_test `
  --pg-bin 'C:\Program Files\PostgreSQL\17\bin' --host localhost --username postgres `
  --backup backups/helpdesk.dump --output results/recovery_demo.json
```

The script uses only the standard library and PostgreSQL utilities. It creates a
custom-format archive, creates a new database from `template0`, and restores in one
transaction with ownership and grants preserved. Source and restore names must be
different lowercase ASCII identifiers of at most 63 characters. Connection strings
are not accepted as database names. Both databases use the same connection/cluster.

Keep the source quiet during this demonstration. Source fingerprints and pg_dump
are separate snapshots, so concurrent changes can fail verification even when the
archive itself is valid. Full-table fingerprints are intended for this 50,000-ticket
dataset. Verification compares all four tables' counts, fingerprints covering every row,
sample records, indexes, sequence values, reporting definitions/results, owners,
and relation/column grants. The restored database then passes the existing schema,
index, and permission smoke tests. These tests roll back records but can advance IDs.

The JSON report records success or failure and the last stage reached. Existing
backup/report files are preserved. An existing restore database is never reused.
If an operation fails, the archive/report and any newly created restore database
remain for inspection; there is no automatic deletion. Retry with new file paths
and a new restore name. The source database is only read.

`restore_database_created` is true only after confirmed creation; null means the
creation command failed and the database's state must be checked before cleanup.

To restore a saved archive later when the source is unavailable, use the native
utilities with a new target name on the same cluster, then run the smoke checks.

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\createdb.exe' -w -h localhost -U postgres -T template0 helpdesk_recovered
& 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe' -w -h localhost -U postgres --exit-on-error --single-transaction -d helpdesk_recovered backups/helpdesk.dump
```

Roles are cluster-wide and are reused on the same cluster. The archive does not
back up global roles, passwords, or server configuration. This is a verified
same-cluster database recovery exercise. Backups stay excluded from Git; keep
verification reports containing synthetic data as project evidence.

The live Python suite also runs recovery using unique temporary restore names and
removes only the restore database created by that test. Run it against a disposable
prepared source using the superuser test login described below.


## Performance, indexing, and monitoring

The new contribution preserves the original schema, data generator, and existing
checks. It adds three reproducible workloads, targeted indexes, a Python benchmark
using only the standard library plus `psql`, and read-only database monitoring.
See [the implementation guide](docs/performance_monitoring.md) for design choices,
measurement limits, monitoring interpretation, and the pgAdmin acceptance checklist.

### Prepare a performance database

Use a disposable database named `helpdesk_perf`. Commands below assume PostgreSQL 17's
`bin` directory is on PATH and run from the repository root. On Windows, add
`C:\Program Files\PostgreSQL\17\bin` to PATH for this terminal or use the full paths
shown above. On macOS/Linux use `python3` if `python` is unavailable. Replace
`postgres` with your local database administrator/owner login.

```sh
createdb -h localhost -U postgres -W helpdesk_perf
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f sql/01_schema.sql
```

Generate the standard sample file using the earlier instructions if it does not exist;
the generator deliberately refuses to overwrite it. Then load and verify:

```sh
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f sample_data/helpdesk_data.sql
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f tests/data_smoke.sql
```

### Benchmark before installing indexes

For noninteractive Python runs, configure PostgreSQL's password file (`.pgpass` on
Unix, `%APPDATA%\postgresql\pgpass.conf` on Windows) or `PGPASSFILE`. Keep credentials
outside the repository and do not place passwords in command-line arguments.
The benchmark uses `psql -w`, so it fails instead of hanging at a password prompt.

```sh
python scripts/benchmark.py --host localhost --username postgres --dbname helpdesk_perf --runs 5 --output results/performance_run_01.json
```

If necessary, specify `--psql` with the full executable path. `--port` is also supported;
standard PostgreSQL connection environment variables supply omitted connection options.

The script compares ticket conversation, reporter history, and active agent queue
queries from `sql/performance_queries.sql`. It creates candidate indexes in one
transaction, checks equal results, collects plans and median timings, then rolls back
the indexes. It creates a JSON report and a Markdown sibling with the comparison and
index sizes. It refuses existing output files and any baseline containing
non-constraint indexes; use another freshly loaded disposable database for later
runs. It never drops existing indexes. SHARE locks block concurrent writers during
the comparison; run this demonstration on the disposable database only.

No measured speedups are supplied with this implementation: live SQL validation was
blocked by this workspace's shared-memory restrictions. Python checks and the setup
failure are recorded in `results/validation.txt` and `results/database_setup.txt`.

### Install and verify indexes

After saving the baseline comparison:

```sh
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f sql/02_indexes.sql
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f tests/index_smoke.sql
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f tests/schema_smoke.sql
```

The index installation is transactional and intended to run once. A repeated run
fails without replacing an existing index. This avoids silently accepting an incorrect
same-name definition. The three indexes target ticket updates by ticket, reporter
history, and active tickets by assigned agent. Extra indexes consume storage and add
write maintenance, so further indexes should follow workload evidence.

### Monitor the database

```sh
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f tests/monitoring_smoke.sql
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f sql/monitoring.sql -o results/monitoring_snapshot_01.txt
```

Use a new snapshot filename for each capture; psql's `-o` replaces an existing file.
The monitoring script covers sessions, long transactions, blocking, locks, table/index
statistics and sizes, maintenance timestamps, and active-ticket backlog. It is plain
SQL and also works in pgAdmin Query Tool. Run in autocommit mode; compare timestamped
snapshots and counter deltas. Coordinate `pg_read_all_stats` membership for a dedicated
monitoring login with the teammate responsible for roles.

For the controlled blocking exercise, follow the separate session instructions in
`sql/blocking_demo.sql`; do not execute the whole file together. All demonstration
row locks are released with ROLLBACK and no ticket data is changed.

### Optional query-level statistics

An administrator can add `pg_stat_statements` to the existing
`shared_preload_libraries` configuration, preserving any other entries, and restart
PostgreSQL. Ensure `compute_query_id` is `auto` or `on`. Then, in `helpdesk_perf`:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;
```

If already installed elsewhere, adjust the qualified view names in the optional
script to its actual schema. Run workloads and then execute:

```sh
psql -X -v ON_ERROR_STOP=1 -h localhost -U postgres -W -d helpdesk_perf -f sql/monitoring_statements.sql
```

This reports high-total-execution-time queries, call counts, execution-time statistics,
and buffer/temp activity. The built-in monitoring module works without this extension.
The monitoring scripts do not change server configuration, reset statistics, or grant roles.

### Run the full test suite

Without a database:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
```

Database tests are skipped unless explicitly configured. After loading the disposable
sample database and installing indexes and permissions, configure its connection using standard
`PGHOST`, `PGPORT`, `PGUSER`, and password-file settings, then enable integration tests.
Use a superuser test login because the permission checks switch between all three groups.
For PowerShell:

```powershell
$env:PGHOST = 'localhost'
$env:PGUSER = 'postgres'
$env:HELPDESK_TEST_DATABASE = 'helpdesk_perf'
# Optional, only after extension setup:
# $env:HELPDESK_TEST_STATEMENTS = '1'
python -m unittest discover -s tests -p 'test_*.py' -v
```

For macOS/Linux:

```sh
PGHOST=localhost PGUSER=postgres HELPDESK_TEST_DATABASE=helpdesk_perf python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Set `HELPDESK_TEST_PSQL` if `psql` is not on PATH, and
`HELPDESK_TEST_STATEMENTS=1` to include the optional extension check. Tests exercise
the original schema/data checks, index definitions and query equivalence, and actual
monitoring queries. The schema test rolls back rows but advances identity sequences.
Tests do not assert unstable timing thresholds or force a particular query plan.

### Added files

- `sql/02_indexes.sql`: three workload-specific indexes.
- `sql/performance_queries.sql`: canonical, deterministically ordered workloads.
- `sql/monitoring.sql`: built-in server and backlog monitoring.
- `sql/monitoring_statements.sql`: optional pg_stat_statements reports.
- `sql/blocking_demo.sql`: bounded, three-session blocking exercise.
- `scripts/benchmark.py`: baseline/indexed comparison and JSON/Markdown reports.
- `tests/index_smoke.sql`, `tests/monitoring_smoke.sql`: database checks.
- `tests/test_benchmark.py`: benchmark logic and failure-handling tests.
- `tests/test_database.py`: opt-in live PostgreSQL integration tests.
- `docs/performance_monitoring.md`: rationale, limitations, and manual checklist.
- `results/database_setup.txt`, `results/validation.txt`: local validation evidence.
- `results/implementation_report.md`: change inventory and outstanding validation.
- `results/git_status.txt`: requested Git status output.
