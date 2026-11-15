import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('benchmark', ROOT / 'scripts/benchmark.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def fixture(runs=3):
    items = [{'kind': 'environment', 'server_version': '17.test', 'database': 'fixture'}]
    for stage in ('baseline', 'indexed'):
        if stage == 'indexed':
            items.append({'kind': 'index_sizes', 'indexes': {'fixture_index': 8192}})
        items.append({'kind': 'result', 'stage': stage, 'workload': 'example',
                      'rows': 2, 'fingerprint': 'same'})
        times = [1000, 9, 3, 6] if stage == 'baseline' else [2000, 3, 1, 2]
        for value in times[:runs + 1]:
            items.append([{'Execution Time': value, 'Planning Time': 0.1,
                           'Plan': {'Node Type': 'Seq Scan', 'Shared Hit Blocks': 5,
                                    'Shared Read Blocks': 0}}])
    return items


class BenchmarkTests(unittest.TestCase):
    def test_canonical_queries_have_stable_ordering(self):
        queries = benchmark.load_workloads()
        self.assertEqual(set(queries), {'ticket_conversation', 'reporter_history', 'active_agent_queue'})
        self.assertTrue(all('ORDER BY' in query for query in queries.values()))

    def test_rejects_non_select_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.sql'
            path.write_text('-- workload: bad\nDELETE FROM public.tickets;\n')
            with self.assertRaises(ValueError):
                benchmark.load_workloads(path)

    def test_rejects_multiple_statements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.sql'
            path.write_text('-- workload: bad\nSELECT 1; SELECT 2;\n')
            with self.assertRaises(ValueError):
                benchmark.load_workloads(path)

    def test_rejects_duplicate_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.sql'
            path.write_text('-- workload: same\nSELECT 1;\n-- workload: same\nSELECT 2;\n')
            with self.assertRaises(ValueError):
                benchmark.load_workloads(path)

    def test_decodes_multiline_psql_json_stream(self):
        expected = fixture()
        self.assertEqual(benchmark.decode_stream('\n'.join(json.dumps(x, indent=2) for x in expected)), expected)

    def test_rejects_non_json_output(self):
        with self.assertRaises(ValueError):
            benchmark.decode_stream('NOTICE: unexpected output')

    def test_medians_exclude_warmup_and_preserve_plans(self):
        report = benchmark.summarize(fixture(), {'example': 'SELECT 1'}, 3)
        self.assertEqual(report['stages']['baseline']['example']['median_execution_ms'], 6)
        self.assertEqual(report['stages']['indexed']['example']['median_execution_ms'], 2)
        self.assertEqual(report['comparisons']['example']['speedup'], 3)
        self.assertEqual(len(report['stages']['baseline']['example']['measured_plans']), 3)
        self.assertIn('| example | 6.000 | 2.000 | 3.00x | yes |', benchmark.markdown_report(report))

    def test_rejects_changed_results(self):
        items = fixture()
        next(x for x in items if isinstance(x, dict) and x.get('stage') == 'indexed')['fingerprint'] = 'different'
        with self.assertRaisesRegex(ValueError, 'results changed'):
            benchmark.summarize(items, {'example': 'SELECT 1'}, 3)

    def test_rejects_empty_workload_results(self):
        items = fixture()
        items[1]['rows'] = 0
        with self.assertRaisesRegex(ValueError, 'no rows'):
            benchmark.summarize(items, {'example': 'SELECT 1'}, 3)

    def test_rejects_extra_output(self):
        with self.assertRaisesRegex(ValueError, 'extra'):
            benchmark.summarize(fixture() + [{}], {'example': 'SELECT 1'}, 3)

    def test_transaction_guards_and_measurement_count(self):
        queries = benchmark.load_workloads()
        sql = benchmark.build_sql(queries, 5)
        self.assertTrue(sql.lstrip().startswith('BEGIN ISOLATION LEVEL REPEATABLE READ;'))
        self.assertTrue(sql.rstrip().endswith('ROLLBACK;'))
        self.assertNotIn('COMMIT;', sql)
        self.assertNotIn('DROP INDEX', sql)
        self.assertIn('IN SHARE MODE', sql)
        self.assertIn('Baseline requires constraint indexes only', sql)
        self.assertNotIn('enable_seqscan = off', sql)
        self.assertEqual(sql.count('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)'), 36)
        self.assertEqual(sql.count('CREATE INDEX '), 3)

    def test_existing_output_is_preserved_before_database_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.json'
            path.write_text('keep this')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/benchmark.py'),
                                     '--dbname', 'unused', '--output', str(path)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), 'keep this')
            self.assertFalse(path.with_suffix('.md').exists())

    def test_database_failure_creates_no_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'failure.json'
            argv = ['benchmark.py', '--dbname', 'unused', '--runs', '3', '--output', str(path)]
            failed = subprocess.CompletedProcess([], 1, stdout='', stderr='server error')
            with patch.object(sys, 'argv', argv), patch.object(benchmark.subprocess, 'run', return_value=failed) as run:
                with self.assertRaises(SystemExit) as failure:
                    benchmark.main()
            self.assertEqual(failure.exception.code, 1)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix('.md').exists())
            self.assertIn('ON_ERROR_STOP=1', run.call_args.args[0])

    def test_success_writes_reports_without_connection_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'success.json'
            argv = ['benchmark.py', '--dbname', 'fixture', '--runs', '3', '--output', str(path)]
            output = '\n'.join(json.dumps(x) for x in fixture())
            success = subprocess.CompletedProcess([], 0, stdout=output, stderr='')
            with patch.object(sys, 'argv', argv), patch.object(benchmark, 'load_workloads', return_value={'example': 'SELECT 1'}), patch.object(benchmark.subprocess, 'run', return_value=success):
                benchmark.main()
            report = json.loads(path.read_text())
            self.assertTrue(report['comparisons']['example']['results_equal'])
            self.assertTrue(path.with_suffix('.md').exists())


if __name__ == '__main__':
    unittest.main()
