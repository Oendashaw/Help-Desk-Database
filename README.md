# PostgreSQL Help Desk Database Administration

CSCE 4355 team project by Oli Endashaw and Moses Ojo.

This project uses a PostgreSQL database to track help desk tickets, staff, and company devices with synthetic data. The planned demonstrations cover database permissions, query performance, monitoring, and backup and restore.

## Prerequisites

- PostgreSQL 17 with the `psql`, `pg_dump`, and `pg_restore` command-line tools
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

Database roles, performance comparisons, monitoring, and backup and restore will be added as those modules are implemented.
