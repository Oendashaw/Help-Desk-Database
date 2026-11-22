"""Opt-in PostgreSQL checks on a prepared, disposable sample database.

Set HELPDESK_TEST_DATABASE and standard PGHOST/PGPORT/PGUSER/PGPASSFILE.
Use a superuser test login; permission checks SET ROLE to each application group.
The schema smoke test advances identity sequences even though rows roll back.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DATABASE = os.environ.get('HELPDESK_TEST_DATABASE')


@unittest.skipUnless(DATABASE, 'set HELPDESK_TEST_DATABASE to a prepared disposable database')
class DatabaseTests(unittest.TestCase):
    def run_sql(self, relative):
        command = [os.environ.get('HELPDESK_TEST_PSQL', shutil.which('psql') or 'psql'),
                   '-X', '-w', '-v', 'ON_ERROR_STOP=1', '--dbname', DATABASE,
                   '-f', str(ROOT / relative)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema(self):
        self.run_sql('tests/schema_smoke.sql')

    def test_permissions(self):
        self.run_sql('tests/permissions_smoke.sql')

    def test_data(self):
        self.run_sql('tests/data_smoke.sql')

    def test_indexes(self):
        self.run_sql('tests/index_smoke.sql')

    def test_indexes_reject_wrong_sort_order(self):
        check = (ROOT / 'tests/index_smoke.sql').read_text(encoding='utf-8')
        indexes = (
            ('idx_updates_ticket_created', 'ticket_updates',
             ('ticket_id', 'created_at', 'update_id'), ('ASC', 'ASC', 'ASC'), ''),
            ('idx_tickets_reporter_created', 'tickets',
             ('reported_by', 'created_at', 'ticket_id'), ('ASC', 'DESC', 'DESC'), ''),
            ('idx_tickets_active_agent_created', 'tickets',
             ('assigned_to', 'created_at', 'ticket_id'), ('ASC', 'DESC', 'DESC'),
             " WHERE status IN ('open', 'in_progress')"),
        )
        for name, table, columns, directions, predicate in indexes:
            for position in range(3):
                with self.subTest(index=name, column=columns[position]):
                    wrong = list(directions)
                    wrong[position] = 'DESC' if wrong[position] == 'ASC' else 'ASC'
                    keys = ', '.join(f'{column} {direction}'
                                     for column, direction in zip(columns, wrong))
                    mutation = (f'DROP INDEX public.{name};\n'
                                f'CREATE INDEX {name} ON public.{table} ({keys}){predicate};\n')
                    # The smoke test's transaction rolls back each deliberately wrong index.
                    sql = check.replace('DO $test$', mutation + 'DO $test$', 1)
                    result = subprocess.run(
                        [os.environ.get('HELPDESK_TEST_PSQL', shutil.which('psql') or 'psql'),
                         '-X', '-w', '-v', 'ON_ERROR_STOP=1', '--dbname', DATABASE],
                        input=sql, capture_output=True, text=True, timeout=120,
                    )
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertIn(f'Incorrect definition for {name}', result.stderr)
        self.run_sql('tests/index_smoke.sql')

    def test_monitoring(self):
        self.run_sql('tests/monitoring_smoke.sql')
        self.run_sql('sql/monitoring.sql')

    def test_optional_statements(self):
        if os.environ.get('HELPDESK_TEST_STATEMENTS') != '1':
            self.skipTest('set HELPDESK_TEST_STATEMENTS=1 after extension setup')
        self.run_sql('sql/monitoring_statements.sql')


if __name__ == '__main__':
    unittest.main()
