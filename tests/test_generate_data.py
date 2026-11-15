import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GENERATOR = Path(__file__).resolve().parents[1] / "scripts" / "generate_data.py"


class GenerateDataTests(unittest.TestCase):
    def test_repeatable_output(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.sql"
            second = Path(directory) / "second.sql"
            for output in (first, second):
                subprocess.run(
                    [sys.executable, str(GENERATOR), str(output)],
                    check=True, capture_output=True, text=True,
                )
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.sql"
            original = b"Keep this existing file.\n"
            output.write_bytes(original)
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(output)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
