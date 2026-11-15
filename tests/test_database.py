"""Opt-in PostgreSQL checks on a prepared, disposable sample database.

Set HELPDESK_TEST_DATABASE and standard PGHOST/PGPORT/PGUSER/PGPASSFILE.
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

    def test_data(self):
        self.run_sql('tests/data_smoke.sql')

    def test_indexes(self):
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
