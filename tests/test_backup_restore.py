import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('recovery', ROOT / 'scripts/backup_restore.py')
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class BackupRestoreTests(unittest.TestCase):
    def arguments(self, directory, source='helpdesk', target='helpdesk_restore_test'):
        return ['backup_restore.py', '--dbname', source, '--restore-db', target,
                '--backup', str(Path(directory) / 'database.dump'),
                '--output', str(Path(directory) / 'report.json')]

    def test_refuses_same_database_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, 'argv', self.arguments(directory, target='helpdesk')):
                with self.assertRaises(SystemExit) as failure:
                    recovery.main()
            self.assertEqual(failure.exception.code, 2)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_refuses_connection_strings_and_maintenance_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            for source, target in (('dbname=helpdesk', 'new_db'), ('helpdesk', 'postgres')):
                with self.subTest(source=source, target=target):
                    with patch.object(sys, 'argv', self.arguments(directory, source, target)):
                        with self.assertRaises(SystemExit) as failure:
                            recovery.main()
                    self.assertEqual(failure.exception.code, 2)

    def test_preserves_existing_artifacts_before_connecting(self):
        for filename in ('database.dump', 'report.json'):
            with self.subTest(file=filename), tempfile.TemporaryDirectory() as directory:
                existing = Path(directory) / filename
                existing.write_bytes(b'keep this')
                with patch.object(sys, 'argv', self.arguments(directory)), patch.object(recovery, 'run_tool') as run:
                    with self.assertRaises(SystemExit):
                        recovery.main()
                    run.assert_not_called()
                self.assertEqual(existing.read_bytes(), b'keep this')
                self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_manifest_detects_changed_data(self):
        recovery.verify_manifest({'tables': {'tickets': 50}}, {'tables': {'tickets': 50}})
        with self.assertRaisesRegex(ValueError, 'tables'):
            recovery.verify_manifest({'tables': {'tickets': 50}}, {'tables': {'tickets': 49}})

    def test_manifest_reads_all_tables_in_one_read_only_transaction(self):
        sql = recovery.manifest_sql()
        self.assertIn('REPEATABLE READ READ ONLY', sql)
        self.assertIn("TIME ZONE 'UTC'", sql)
        for table, key in recovery.TABLES:
            self.assertIn(f'FROM public.{table}', sql)
            self.assertIn(f'ORDER BY {key}', sql)
        self.assertNotRegex(sql, r'\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|CREATE)\b')

    def test_success_preserves_restore_safety_options(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = {'superuser': True, 'server_major': 17, 'tables': {}}
            with patch.object(sys, 'argv', self.arguments(directory)), \
                 patch.object(recovery.shutil, 'which', side_effect=lambda name, **kw: name), \
                 patch.object(recovery, 'inspect_database', return_value=fixture), \
                 patch.object(recovery, 'run_tool', return_value='') as run:
                recovery.main()
            report = json.loads((Path(directory) / 'report.json').read_text())
            self.assertTrue(report['success'])
            self.assertEqual(len(report['checks_passed']), 3)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual([command[0] for command in commands[:3]], ['pg_dump', 'createdb', 'pg_restore'])
            self.assertIn('--format=custom', commands[0])
            self.assertIn('--template=template0', commands[1])
            self.assertIn('--single-transaction', commands[2])
            self.assertIn('--exit-on-error', commands[2])
            self.assertFalse(any('--clean' in command or '--no-acl' in command for command in commands))
            self.assertEqual(report['source'], report['restored'])

    def test_failed_restore_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = {'superuser': True, 'server_major': 17, 'tables': {}}

            def fail_restore(command, **kwargs):
                if command[0] == 'pg_restore':
                    raise RuntimeError('simulated restore failure')
                return ''

            with patch.object(sys, 'argv', self.arguments(directory)), \
                 patch.object(recovery.shutil, 'which', side_effect=lambda name, **kw: name), \
                 patch.object(recovery, 'inspect_database', return_value=fixture), \
                 patch.object(recovery, 'run_tool', side_effect=fail_restore):
                with self.assertRaises(SystemExit) as failure:
                    recovery.main()
            self.assertEqual(failure.exception.code, 1)
            report = json.loads((Path(directory) / 'report.json').read_text())
            self.assertFalse(report['success'])
            self.assertTrue(report['restore_database_created'])
            self.assertEqual(report['stage'], 'restore')
            self.assertTrue((Path(directory) / 'database.dump').exists())


if __name__ == '__main__':
    unittest.main()
