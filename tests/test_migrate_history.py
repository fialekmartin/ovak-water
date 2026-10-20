import importlib.util
import unittest
from datetime import date
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'migrate_history.py'
spec = importlib.util.spec_from_file_location('ovak_migrate_history', MODULE)
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


class MigrationTests(unittest.TestCase):
    def test_valid_consecutive_days(self):
        data = {date(2026, 10, 18): 100, date(2026, 10, 19): 200}
        migrate.validate_days(data, date(2026, 10, 18), date(2026, 10, 19))
        exported = migrate.build_export(data, date(2026, 10, 18), date(2026, 10, 19))
        self.assertEqual(2, exported['count'])
        self.assertEqual(0.2, exported['history'][1]['m3'])

    def test_missing_day_blocks_import(self):
        with self.assertRaisesRegex(ValueError, 'Chybějící odečty'):
            migrate.validate_days({date(2026, 10, 18): 100}, date(2026, 10, 18), date(2026, 10, 19))

    def test_apply_requires_confirmation(self):
        with self.assertRaises(SystemExit) as error:
            migrate.main(['--apply', '--from', '2026-10-01', '--to', '2026-10-19'])
        self.assertEqual(2, error.exception.code)


if __name__ == '__main__':
    unittest.main()
