import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


class BackupWriterLifecycleTests(SimpleTestCase):
    """Exercise the backup script, including its failure trap, without a real DB."""

    def run_backup(self, running, fail_dump=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            script = Path(__file__).resolve().parents[3] / 'scripts' / 'backup.sh'
            shutil.copyfile(script, root / 'scripts' / 'backup.sh')
            command = root / 'docker'
            command.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['BACKUP_TEST_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if 'ps' in args:
    print(os.environ['BACKUP_TEST_RUNNING'])
elif 'start' in args and '--wait' in args:
    sys.stderr.write('unknown flag: --wait\\n')
    sys.exit(1)
elif 'pg_dump' in ' '.join(args):
    if os.environ['BACKUP_TEST_FAIL'] == '1':
        sys.exit(7)
    sys.stdout.buffer.write(b'fake verified dump')
elif args[:2] == ['volume', 'inspect']:
    sys.exit(1)
''')
            command.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       BACKUP_TEST_LOG=str(root / 'calls'),
                       BACKUP_TEST_RUNNING='\n'.join(running),
                       BACKUP_TEST_FAIL='1' if fail_dump else '0')
            result = subprocess.run(['bash', str(root / 'scripts' / 'backup.sh')],
                                    env=env, capture_output=True, text=True, timeout=20)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
            return result, calls

    def test_stops_both_writers_before_snapshot_and_restores_running_set(self):
        result, calls = self.run_backup(['db', 'web', 'reminders'])
        self.assertEqual(result.returncode, 0, result.stderr)
        stops = [(i, args) for i, args in enumerate(calls) if 'stop' in args]
        self.assertEqual([args[-1] for _, args in stops], ['reminders', 'web'])
        dump_index = next(i for i, args in enumerate(calls) if 'pg_dump' in ' '.join(args))
        self.assertTrue(all(i < dump_index for i, _ in stops))
        start = next(args for args in calls if 'start' in args)
        self.assertEqual(start[-2:], ['web', 'reminders'])
        self.assertNotIn('--wait', start)
        self.assertNotIn('Relancez DEMARRER_TVM.cmd', result.stderr)

    def test_failed_snapshot_still_resumes_both_previously_running_services(self):
        result, calls = self.run_backup(['db', 'web', 'reminders'], fail_dump=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls[-1][-2:], ['web', 'reminders'])
        self.assertIn('start', calls[-1])

    def test_stopped_worker_is_not_started_by_backup(self):
        result, calls = self.run_backup(['db', 'web'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('reminders', [item for args in calls for item in args])
        self.assertEqual(calls[-1][-1], 'web')

    def test_no_writers_running_does_not_start_application(self):
        result, calls = self.run_backup(['db'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('start' in args or 'stop' in args for args in calls))
