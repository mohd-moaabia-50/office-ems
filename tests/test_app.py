"""Run with: python -m unittest discover -s tests -v"""
import csv
import io
import os
import secrets
import tempfile
import unittest
from pathlib import Path

from app import create_app, create_user, get_db
from flask import g
from werkzeug.security import check_password_hash


class OfficeEMSTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.password = secrets.token_urlsafe(20)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': secrets.token_hex(32),
                               'DATABASE': str(Path(self.directory.name) / 'test.db'),
                               'DEMO_MODE': True})
        with self.app.app_context():
            g.app_database = self.app.config['DATABASE']
            for role in ('Admin', 'HR', 'Manager'):
                create_user('test_' + role.lower(), self.password, role)
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def post(self, client, path, data=None, follow=True):
        client.get('/login')
        with client.session_transaction() as state:
            token = state['csrf_token']
        return client.post(path, data={'csrf_token': token, **(data or {})}, follow_redirects=follow)

    def login(self, client=None, role='Admin', password=None):
        return self.post(client or self.client, '/login',
                         {'username': 'test_' + role.lower(), 'password': password or self.password})

    def query(self, sql, params=()):
        with self.app.app_context():
            g.app_database = self.app.config['DATABASE']
            return get_db().execute(sql, params).fetchall()

    def employee_data(self, **overrides):
        return {'employee_code':'TEST001', 'full_name':'Fictional Test Employee',
                'dept_id':'1', 'designation_id':'1', 'phone':'', 'email':'',
                'join_date':'2026-01-01', 'salary':'50000.50',
                'employment_status':'Active', 'address':'Demo address', **overrides}

    def test_authentication_and_pages(self):
        self.assertEqual(self.client.get('/employees').status_code, 302)
        self.assertEqual(self.client.post('/login', data={}).status_code, 400)
        self.assertIn(b'Invalid username or password', self.login(password=secrets.token_hex(20)).data)
        self.assertIn(b'Developed by Mohd Moaabia', self.login().data)
        self.assertIn(b'Mohd Moaabia', self.client.get('/').data)
        for path in ['/', '/employees', '/employees/new', '/employees/1/edit',
                     '/employees/1/delete', '/attendance', '/payroll', '/password']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get('/health').json, {'status':'ok'})
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.post(self.client, '/logout')
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_password_change_and_session_revocation(self):
        self.login()
        other = self.app.test_client()
        self.login(other)
        new_password = secrets.token_urlsafe(24)
        result = self.post(self.client, '/password', {'current_password':'incorrect',
                           'new_password':new_password, 'confirm_password':new_password})
        self.assertIn(b'Current password is incorrect', result.data)
        result = self.post(self.client, '/password', {'current_password':self.password,
                           'new_password':new_password, 'confirm_password':'mismatch'})
        self.assertIn(b'New passwords do not match', result.data)
        result = self.post(self.client, '/password', {'current_password':self.password,
                           'new_password':'short', 'confirm_password':'short'})
        self.assertIn(b'12 and 128', result.data)
        result = self.post(self.client, '/password', {'current_password':self.password,
                           'new_password':new_password, 'confirm_password':new_password})
        self.assertIn(b'Password changed', result.data)
        self.assertEqual(other.get('/employees').status_code, 302)
        stored = self.query("SELECT password_hash FROM users WHERE username='test_admin'")[0][0]
        self.assertNotEqual(stored, new_password)
        self.assertTrue(check_password_hash(stored, new_password))
        self.assertFalse(check_password_hash(stored, self.password))
        self.assertIn(b'Invalid username or password', self.login().data)
        self.assertEqual(self.login(password=new_password).status_code, 200)

    def test_employee_crud_and_validation(self):
        self.login()
        self.assertIn(b'Employee saved', self.post(self.client, '/employees/new', self.employee_data()).data)
        emp_id = self.query("SELECT emp_id FROM employees WHERE employee_code='TEST001'")[0][0]
        self.assertIn(b'Fictional Test Employee', self.client.get('/employees?q=TEST001').data)
        self.assertIn(b'already in use', self.post(self.client, '/employees/new', self.employee_data()).data)
        for salary in ['NaN', 'inf', '-1', 'not-a-number']:
            self.assertEqual(len(self.query('SELECT * FROM employees')), 5)
            self.post(self.client, '/employees/new', self.employee_data(employee_code='INVALID', salary=salary))
            self.assertEqual(len(self.query('SELECT * FROM employees')), 5)
        self.assertIn(b'Employee saved', self.post(self.client, f'/employees/{emp_id}/edit',
                                                  self.employee_data(full_name='Updated Demo Employee')).data)
        self.post(self.client, '/attendance', {'emp_id':str(emp_id), 'att_date':'2026-01-01','status':'WFH','remarks':''})
        self.post(self.client, '/payroll', {'emp_id':str(emp_id), 'pay_month':'2026-01', 'allowance':'0','deduction':'0','payment_status':'Pending'})
        self.post(self.client, f'/employees/{emp_id}/delete')
        self.assertFalse(self.query('SELECT * FROM employees WHERE emp_id=?', (emp_id,)))
        self.assertFalse(self.query('SELECT * FROM attendance WHERE emp_id=?', (emp_id,)))
        self.assertFalse(self.query('SELECT * FROM payroll WHERE emp_id=?', (emp_id,)))
        self.assertEqual(self.client.get('/employees/999/edit').status_code, 404)

    def test_attendance_upsert_and_payroll(self):
        self.login()
        data = {'emp_id':'1', 'att_date':'2026-01-01','status':'Present','remarks':'demo'}
        self.post(self.client, '/attendance', data)
        self.post(self.client, '/attendance', {**data, 'status':'WFH'})
        rows = self.query("SELECT * FROM attendance WHERE emp_id=1 AND att_date='2026-01-01'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'WFH')
        self.post(self.client, '/attendance', {**data, 'att_date':'bad-date'})
        self.post(self.client, '/attendance', {**data, 'status':'Invalid'})
        payroll = {'emp_id':'1', 'pay_month':'2026-01','allowance':'1500.25','deduction':'500.10','payment_status':'Paid'}
        self.post(self.client, '/payroll', payroll)
        self.post(self.client, '/payroll', payroll)
        rows = self.query("SELECT * FROM payroll WHERE emp_id=1 AND pay_month='2026-01'")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]['net_salary'], 46000.15)
        self.assertIn(b'Deduction cannot exceed', self.post(self.client, '/payroll', {**payroll,'deduction':'9999999'}).data)
        self.assertIn(b'valid month', self.post(self.client, '/payroll', {**payroll,'pay_month':'2026-99'}).data)

    def test_manager_permissions_and_hr_permissions(self):
        self.login(role='Manager')
        for path in ['/employees/new','/employees/1/edit','/employees/1/delete','/payroll','/export/payroll.csv']:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.post(self.client, '/attendance', {}, follow=False).status_code, 403)
        self.assertNotIn(b'45,000.00', self.client.get('/employees').data)
        csv_data = self.client.get('/export/employees.csv').data.decode('utf-8-sig')
        self.assertNotIn('salary', csv_data.splitlines()[0])
        self.assertEqual(self.client.get('/export/attendance.csv').status_code, 200)
        self.post(self.client, '/logout')
        self.login(role='HR')
        self.assertEqual(self.client.get('/employees/new').status_code, 200)
        self.assertEqual(self.client.get('/payroll').status_code, 200)

    def test_csv_escaping_and_html_escaping(self):
        self.login()
        self.post(self.client, '/employees/new', self.employee_data(full_name='=SUM(1,2)',address='<script>alert(1)</script>'))
        result = self.client.get('/export/employees.csv')
        self.assertEqual(result.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(result.data.decode('utf-8-sig'))))
        row = next(row for row in rows if row['employee_code']=='TEST001')
        self.assertEqual(row['full_name'], "'=SUM(1,2)")
        html = self.client.get('/employees').data
        self.assertNotIn(b'<script>alert(1)</script>', html)
        self.assertIn(b'&lt;script&gt;', html)
        self.assertEqual(self.client.get('/export/unknown.csv').status_code, 404)

    def test_login_cooldown(self):
        for _ in range(5):
            self.login(password='incorrect')
        self.assertEqual(self.login().status_code, 429)

    def test_data_persists_across_restart_and_different_working_directory(self):
        self.login()
        self.post(self.client, '/employees/new', self.employee_data())
        original_directory = os.getcwd()
        try:
            os.chdir(self.directory.name)
            restarted = create_app({'TESTING':True, 'SECRET_KEY':self.app.config['SECRET_KEY'],
                                    'DATABASE':self.app.config['DATABASE'], 'DEMO_MODE':True})
            client = restarted.test_client()
            self.login(client)
            self.assertIn(b'Fictional Test Employee', client.get('/employees?q=TEST001').data)
        finally:
            os.chdir(original_directory)
        self.assertTrue(Path(restarted.config['DATABASE']).is_absolute())

    def test_startup_does_not_overwrite_changed_password(self):
        self.login()
        new = secrets.token_urlsafe(24)
        self.post(self.client, '/password', {'current_password':self.password,'new_password':new,'confirm_password':new})
        create_app({'TESTING':True, 'SECRET_KEY':self.app.config['SECRET_KEY'],
                    'DATABASE':self.app.config['DATABASE'], 'DEMO_MODE':True})
        self.assertEqual(self.login(password=new).status_code, 200)
        self.assertEqual(len(self.query('SELECT * FROM employees')), 4)


if __name__ == '__main__':
    unittest.main()
