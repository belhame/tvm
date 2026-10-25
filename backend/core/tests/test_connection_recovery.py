import importlib.util
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import psycopg
from django.test import SimpleTestCase


module_path = Path(__file__).resolve().parents[3] / 'scripts' / 'check_database_connection.py'
spec = importlib.util.spec_from_file_location('tvm_connection_check', module_path)
connection_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connection_check)


class ConnectionRecoveryDiagnosticTests(SimpleTestCase):
    connection_string = 'postgresql://tvm:PRIVATE_TEST_PASSWORD@db:5432/tvm'

    def check(self, side_effect, connection_string=None):
        output = io.StringIO()
        with patch.dict(os.environ, {
            'DATABASE_URL': connection_string or self.connection_string,
            'POSTGRES_USER': 'tvm', 'POSTGRES_DB': 'tvm',
            'POSTGRES_PASSWORD': 'PRIVATE_TEST_PASSWORD',
        }):
            with patch.object(connection_check, 'query', side_effect=side_effect) as query:
                with redirect_stdout(output):
                    code = connection_check.main()
        self.assertNotIn('PRIVATE_TEST_PASSWORD', output.getvalue())
        self.assertNotIn('postgresql://', output.getvalue())
        return code, query

    def test_rejects_other_hosts_or_connection_options_before_connecting(self):
        for target in (
            'postgresql://tvm:PRIVATE_TEST_PASSWORD@example.invalid/tvm',
            'postgresql://tvm:PRIVATE_TEST_PASSWORD@127.0.0.1/tvm',
            self.connection_string + '?host=example.invalid',
            'postgresql://tvm:PRIVATE_TEST_PASSWORD@db:5433/tvm',
            'postgresql://tvm:PRIVATE_TEST_PASSWORD@db:invalid/tvm',
            'not-a-connection-string',
            'postgresql://other:PRIVATE_TEST_PASSWORD@db:5432/tvm',
            'postgresql://tvm:PRIVATE_TEST_PASSWORD@db:5432/other',
            'postgresql://tvm:another-password@db:5432/tvm',
        ):
            with self.subTest(target=target):
                code, query = self.check(None, target)
                self.assertEqual(code, 20)
                query.assert_not_called()

    def test_startup_auth_error_without_sqlstate_is_recognized_without_echoing_it(self):
        error = psycopg.OperationalError('password authentication failed PRIVATE_TEST_PASSWORD')
        self.assertIsNone(error.sqlstate)
        code, query = self.check(error)
        self.assertEqual(code, 10)
        self.assertEqual(query.call_count, 1)

    def test_other_network_errors_do_not_authorize_password_repair(self):
        code, _ = self.check(psycopg.OperationalError('connection refused PRIVATE_TEST_PASSWORD'))
        self.assertEqual(code, 20)

    def test_correct_password_and_rejected_witness_are_required(self):
        code, query = self.check([None, psycopg.OperationalError('password authentication failed')])
        self.assertEqual(code, 0)
        self.assertEqual(query.call_count, 2)
        self.assertIn('password', query.call_args.kwargs)
        self.assertNotEqual(query.call_args.kwargs['password'], 'PRIVATE_TEST_PASSWORD')

    def test_connection_with_wrong_password_is_not_reported_as_verified(self):
        code, _ = self.check([None, None])
        self.assertEqual(code, 30)

    def test_unavailable_witness_is_not_reported_as_verified(self):
        code, _ = self.check([None, psycopg.OperationalError('connection refused')])
        self.assertEqual(code, 20)

    def test_real_query_uses_read_only_transaction_and_does_not_query_business_tables(self):
        with patch.object(connection_check.psycopg, 'connect') as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = (1,)
            connection_check.query(self.connection_string)
            self.assertEqual(connect.call_args.kwargs['options'], '-c default_transaction_read_only=on')
            cursor.execute.assert_called_once_with('SELECT 1')
