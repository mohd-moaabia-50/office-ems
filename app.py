"""OfficeEMS: a small Flask/SQLite portfolio demo with synthetic seed data."""
import csv
import io
import os
import re
import secrets
import sqlite3
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ('Admin', 'HR', 'Manager')
ATTENDANCE_STATUSES = ('Present', 'Absent', 'Leave', 'WFH')
EMPLOYEE_STATUSES = ('Active', 'Inactive')
PAYMENT_STATUSES = ('Pending', 'Paid')
EMPLOYEE_QUERY = '''SELECT e.*, d.dept_name, x.title FROM employees e
    JOIN departments d ON d.dept_id=e.dept_id
    JOIN designations x ON x.designation_id=e.designation_id'''
ATTENDANCE_QUERY = '''SELECT a.*, e.employee_code, e.full_name FROM attendance a
    JOIN employees e ON e.emp_id=a.emp_id'''
PAYROLL_QUERY = '''SELECT p.*, e.employee_code, e.full_name FROM payroll p
    JOIN employees e ON e.emp_id=p.emp_id'''


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(g.app_database, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def init_db():
    db = get_db()
    schema = Path(__file__).with_name('schema.sql').read_text()
    db.executescript(schema)
    db.commit()


def seed_demo():
    """Populate a new database only. Never import the desktop database."""
    db = get_db()
    if db.execute('SELECT COUNT(*) FROM employees').fetchone()[0]:
        return
    with db:
        db.executemany('INSERT OR IGNORE INTO departments(dept_name, location) VALUES (?,?)',
                       [('IT', 'Demo floor 1'), ('HR', 'Demo floor 2'),
                        ('Finance', 'Demo floor 3'), ('Operations', 'Demo floor 4')])
        db.executemany('INSERT OR IGNORE INTO designations(title, grade) VALUES (?,?)',
                       [('Software Engineer', 'G5'), ('HR Executive', 'G4'),
                        ('Accountant', 'G4'), ('Manager', 'G7')])
        departments = dict(db.execute('SELECT dept_name, dept_id FROM departments'))
        designations = dict(db.execute('SELECT title, designation_id FROM designations'))
        people = [('Demo Employee One', 'IT', 'Software Engineer', 45000),
                  ('Demo Employee Two', 'HR', 'HR Executive', 35000),
                  ('Demo Employee Three', 'Finance', 'Accountant', 38000),
                  ('Demo Employee Four', 'Operations', 'Manager', 52000)]
        for i, (name, department, title, salary) in enumerate(people, 1):
            cur = db.execute('''INSERT INTO employees(employee_code, full_name, dept_id,
                designation_id, phone, email, join_date, salary, employment_status, address)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (f'DEMO{i:03}', name, departments[department], designations[title], '',
                 f'demo{i}@example.invalid', str(date.today() - timedelta(days=90)),
                 salary, 'Active', 'Fictional demo office'))
            for day in range(7):
                db.execute('INSERT INTO attendance(emp_id, att_date, status, remarks) VALUES (?,?,?,?)',
                           (cur.lastrowid, str(date.today() - timedelta(days=day)),
                            ATTENDANCE_STATUSES[(day + i - 1) % 4], 'Synthetic demo record'))
            db.execute('''INSERT INTO payroll(emp_id,pay_month,basic_salary,allowance,
                deduction,net_salary,payment_status) VALUES (?,?,?,?,?,?,?)''',
                (cur.lastrowid, date.today().strftime('%Y-%m'), salary, 1500, 500,
                 salary + 1000, 'Pending'))


def password_error(password):
    if not 12 <= len(password) <= 128:
        return 'Use a password between 12 and 128 characters.'
    return None


def create_user(username, password, role):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', username):
        raise ValueError('Username must contain 3-40 letters, numbers, dots, underscores or hyphens.')
    error = password_error(password)
    if error:
        raise ValueError(error)
    if role not in ROLES:
        raise ValueError('Choose Admin, HR or Manager.')
    db = get_db()
    with db:
        display_name = 'Mohd Moaabia' if role == 'Admin' else username
        db.execute('INSERT INTO users(username,display_name,password_hash,role) VALUES (?,?,?,?)',
                   (username, display_name, generate_password_hash(password), role))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user['role'] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def form_text(key, limit=200, required=False):
    value = request.form.get(key, '').strip()
    if required and not value:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is required.")
    if len(value) > limit:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is too long.")
    return value


def money(key, default=None):
    raw = form_text(key, 30) or default
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValueError(f'{key.capitalize()} must be a number.')
    if not value.is_finite() or value < 0 or value > Decimal('1000000000'):
        raise ValueError(f'{key.capitalize()} must be between 0 and 1,000,000,000.')
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def form_choice(key, choices):
    value = form_text(key, required=True)
    if value not in choices:
        raise ValueError(f"Choose a valid {key.replace('_', ' ')}.")
    return value


def employee_id():
    try:
        value = int(request.form.get('emp_id', ''))
    except ValueError:
        raise ValueError('Choose an employee.')
    if not get_db().execute('SELECT 1 FROM employees WHERE emp_id=?', (value,)).fetchone():
        raise ValueError('Employee not found.')
    return value


def get_employee(emp_id):
    row = get_db().execute('SELECT * FROM employees WHERE emp_id=?', (emp_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def safe_csv_cell(value):
    # Spreadsheet programs can execute formula-like cells, even in a CSV.
    text = '' if value is None else str(value)
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        DATABASE=os.environ.get('DATABASE_PATH', str(Path(app.instance_path) / 'office_ems.db')),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'false').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
        MAX_CONTENT_LENGTH=128 * 1024,
        DEMO_MODE=os.environ.get('DEMO_MODE', 'true').lower() == 'true',
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('Set SECRET_KEY to a random value at least 32 characters long. See README.md.')
    # Pin even a relative configured path to the application folder, not the shell's cwd.
    configured_path = Path(app.config['DATABASE']).expanduser()
    if not configured_path.is_absolute():
        configured_path = Path(app.root_path) / configured_path
    app.config['DATABASE'] = str(configured_path.resolve())
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def load_user_and_protect_forms():
        g.app_database = app.config['DATABASE']
        g.user = None
        if session.get('user_id'):
            user = get_db().execute('SELECT * FROM users WHERE user_id=?', (session['user_id'],)).fetchone()
            if user and user['session_version'] == session.get('session_version'):
                g.user = user
            else:
                session.clear()
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        if request.method == 'POST':
            provided = request.form.get('csrf_token', '')
            if not secrets.compare_digest(provided, session['csrf_token']):
                abort(400, description='Form expired. Reload the page and try again.')

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        if app.config['SESSION_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.context_processor
    def shared_context():
        return dict(user=g.user, csrf_token=session.get('csrf_token'), today=date.today(),
                    demo_mode=app.config['DEMO_MODE'],
                    can_write=g.user is not None and g.user['role'] in ('Admin', 'HR'))

    @app.template_filter('amount')
    def amount(value):
        return f'{value:,.2f}'

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def friendly_error(error):
        return render_template('error.html', error=error), error.code

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()[:40]
            password = request.form.get('password', '')
            db = get_db()
            now = int(time.time())
            # Database-backed per-username cooldown; no trust in forwarded IP headers.
            attempt = db.execute('SELECT * FROM login_attempts WHERE username=?', (username,)).fetchone()
            if attempt and attempt['attempts'] >= 5 and now - attempt['started_at'] < 300:
                abort(429, description='Too many login attempts. Wait five minutes and try again.')
            user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            if len(password) <= 128 and user and check_password_hash(user['password_hash'], password):
                with db:
                    db.execute('DELETE FROM login_attempts WHERE username=?', (username,))
                session.clear()
                session.update(user_id=user['user_id'], session_version=user['session_version'],
                               csrf_token=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect(url_for('dashboard'))
            with db:
                db.execute('DELETE FROM login_attempts WHERE started_at<?', (now - 300,))
                db.execute('''INSERT INTO login_attempts(username, attempts, started_at) VALUES (?,1,?)
                    ON CONFLICT(username) DO UPDATE SET attempts=attempts+1''', (username, now))
            flash('Invalid username or password.', 'error')
        return render_template('login.html')

    @app.post('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            current = request.form.get('current_password', '')
            new = request.form.get('new_password', '')
            confirmation = request.form.get('confirm_password', '')
            error = password_error(new)
            if len(current) > 128 or not check_password_hash(g.user['password_hash'], current):
                error = 'Current password is incorrect.'
            elif new != confirmation:
                error = 'New passwords do not match.'
            elif new == current:
                error = 'Choose a password different from your current password.'
            if error:
                flash(error, 'error')
            else:
                db = get_db()
                with db:
                    db.execute('''UPDATE users SET password_hash=?, session_version=session_version+1
                        WHERE user_id=?''', (generate_password_hash(new), g.user['user_id']))
                session.clear()
                flash('Password changed. Sign in with your new password.', 'success')
                return redirect(url_for('login'))
        return render_template('password.html')

    @app.get('/')
    @login_required
    def dashboard():
        db = get_db()
        counts = {'total': db.execute('SELECT COUNT(*) FROM employees').fetchone()[0],
                  'active': db.execute("SELECT COUNT(*) FROM employees WHERE employment_status='Active'").fetchone()[0],
                  'present': db.execute("SELECT COUNT(*) FROM attendance WHERE status='Present' AND att_date=?", (str(date.today()),)).fetchone()[0]}
        if g.user['role'] in ('Admin', 'HR'):
            counts['pending'] = db.execute("SELECT COUNT(*) FROM payroll WHERE payment_status='Pending'").fetchone()[0]
        recent = db.execute(ATTENDANCE_QUERY + ' ORDER BY att_date DESC, full_name LIMIT 8').fetchall()
        return render_template('dashboard.html', counts=counts, recent=recent)

    @app.get('/employees')
    @login_required
    def employees():
        keyword = request.args.get('q', '').strip()[:100]
        query = EMPLOYEE_QUERY
        params = ()
        if keyword:
            query += ' WHERE e.full_name LIKE ? OR e.employee_code LIKE ? OR d.dept_name LIKE ? OR x.title LIKE ?'
            params = (f'%{keyword}%',) * 4
        rows = get_db().execute(query + ' ORDER BY e.emp_id DESC', params).fetchall()
        return render_template('employees.html', employees=rows, keyword=keyword)

    @app.route('/employees/new', methods=['GET', 'POST'])
    @app.route('/employees/<int:emp_id>/edit', methods=['GET', 'POST'])
    @roles_required('Admin', 'HR')
    def employee_form(emp_id=None):
        db = get_db()
        employee = dict(get_employee(emp_id)) if emp_id else {'join_date': str(date.today()), 'employment_status': 'Active'}
        departments = db.execute('SELECT * FROM departments ORDER BY dept_name').fetchall()
        designations = db.execute('SELECT * FROM designations ORDER BY title').fetchall()
        if request.method == 'POST':
            employee.update(request.form.to_dict())
            try:
                code = form_text('employee_code', 30, True)
                name = form_text('full_name', 100, True)
                dept = int(form_text('dept_id', 10, True))
                designation = int(form_text('designation_id', 10, True))
                if dept not in [d['dept_id'] for d in departments] or designation not in [d['designation_id'] for d in designations]:
                    raise ValueError('Choose a valid department and designation.')
                email = form_text('email', 254)
                if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                    raise ValueError('Enter a valid email address.')
                join_date = date.fromisoformat(form_text('join_date', 10, True)).isoformat()
                data = (code, name, dept, designation, form_text('phone', 30), email or None,
                        join_date, float(money('salary')), form_choice('employment_status', EMPLOYEE_STATUSES),
                        form_text('address', 500))
                with db:
                    if emp_id:
                        db.execute('''UPDATE employees SET employee_code=?,full_name=?,dept_id=?,designation_id=?,
                            phone=?,email=?,join_date=?,salary=?,employment_status=?,address=? WHERE emp_id=?''', data + (emp_id,))
                    else:
                        db.execute('''INSERT INTO employees(employee_code,full_name,dept_id,designation_id,
                            phone,email,join_date,salary,employment_status,address) VALUES (?,?,?,?,?,?,?,?,?,?)''', data)
                flash('Employee saved.', 'success')
                return redirect(url_for('employees'))
            except ValueError as error:
                flash(str(error), 'error')
            except sqlite3.IntegrityError:
                flash('Employee code or email is already in use.', 'error')
        return render_template('employee_form.html', employee=employee, emp_id=emp_id,
                               departments=departments, designations=designations)

    @app.route('/employees/<int:emp_id>/delete', methods=['GET', 'POST'])
    @roles_required('Admin', 'HR')
    def delete_employee(emp_id):
        employee = get_employee(emp_id)
        if request.method == 'POST':
            db = get_db()
            with db:
                db.execute('DELETE FROM employees WHERE emp_id=?', (emp_id,))
            flash('Employee and linked attendance/payroll records deleted.', 'success')
            return redirect(url_for('employees'))
        return render_template('delete_employee.html', employee=employee)

    @app.route('/attendance', methods=['GET', 'POST'])
    @login_required
    def attendance():
        db = get_db()
        if request.method == 'POST':
            if g.user['role'] not in ('Admin', 'HR'):
                abort(403)
            try:
                emp_id = employee_id()
                att_date = date.fromisoformat(form_text('att_date', 10, True)).isoformat()
                status = form_choice('status', ATTENDANCE_STATUSES)
                remarks = form_text('remarks', 300)
                with db:
                    db.execute('''INSERT INTO attendance(emp_id,att_date,status,remarks) VALUES (?,?,?,?)
                        ON CONFLICT(emp_id,att_date) DO UPDATE SET status=excluded.status,remarks=excluded.remarks''',
                        (emp_id, att_date, status, remarks))
                flash('Attendance saved. An existing record for this employee and date is updated.', 'success')
                return redirect(url_for('attendance'))
            except ValueError as error:
                flash(str(error), 'error')
        rows = db.execute(ATTENDANCE_QUERY + ' ORDER BY att_date DESC, full_name').fetchall()
        lookup = db.execute('SELECT emp_id,employee_code,full_name FROM employees ORDER BY full_name').fetchall()
        return render_template('attendance.html', records=rows, lookup=lookup, statuses=ATTENDANCE_STATUSES)

    @app.route('/payroll', methods=['GET', 'POST'])
    @roles_required('Admin', 'HR')
    def payroll():
        db = get_db()
        if request.method == 'POST':
            try:
                emp_id = employee_id()
                month = form_text('pay_month', 7, True)
                if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month) or int(month[:4]) < 1:
                    raise ValueError('Enter a valid month in YYYY-MM format.')
                allowance, deduction = money('allowance', '0'), money('deduction', '0')
                basic = Decimal(str(get_employee(emp_id)['salary']))
                net = basic + allowance - deduction
                if net < 0:
                    raise ValueError('Deduction cannot exceed salary plus allowance.')
                status = form_choice('payment_status', PAYMENT_STATUSES)
                with db:
                    db.execute('''INSERT INTO payroll(emp_id,pay_month,basic_salary,allowance,deduction,net_salary,payment_status)
                        VALUES (?,?,?,?,?,?,?) ON CONFLICT(emp_id,pay_month) DO UPDATE SET
                        basic_salary=excluded.basic_salary,allowance=excluded.allowance,deduction=excluded.deduction,
                        net_salary=excluded.net_salary,payment_status=excluded.payment_status''',
                        (emp_id, month, float(basic), float(allowance), float(deduction), float(net), status))
                flash('Payroll saved. An existing record for this employee and month is updated.', 'success')
                return redirect(url_for('payroll'))
            except ValueError as error:
                flash(str(error), 'error')
        rows = db.execute(PAYROLL_QUERY + ' ORDER BY pay_month DESC, full_name').fetchall()
        lookup = db.execute('SELECT emp_id,employee_code,full_name FROM employees ORDER BY full_name').fetchall()
        return render_template('payroll.html', records=rows, lookup=lookup, statuses=PAYMENT_STATUSES)

    @app.get('/export/<report>.csv')
    @login_required
    def export_csv(report):
        if report not in ('employees', 'attendance', 'payroll'):
            abort(404)
        if report == 'payroll' and g.user['role'] not in ('Admin', 'HR'):
            abort(403)
        headers = {
            'employees': ['employee_code','full_name','dept_name','title','phone','email','join_date','employment_status','address'],
            'attendance': ['employee_code','full_name','att_date','status','remarks'],
            'payroll': ['employee_code','full_name','pay_month','basic_salary','allowance','deduction','net_salary','payment_status'],
        }[report]
        if report == 'employees' and g.user['role'] in ('Admin', 'HR'):
            headers = headers + ['salary']
        query = {'employees': EMPLOYEE_QUERY, 'attendance': ATTENDANCE_QUERY, 'payroll': PAYROLL_QUERY}[report]
        rows = get_db().execute(query).fetchall()
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows([[safe_csv_cell(row[key]) for key in headers] for row in rows])
        return Response('\ufeff' + stream.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={report}_report.csv'})

    @app.cli.command('create-user')
    @click.option('--username', prompt=True)
    @click.option('--role', type=click.Choice(ROLES), prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_user_command(username, role, password):
        """Create a user without storing passwords in source code."""
        g.app_database = app.config['DATABASE']
        try:
            create_user(username, password, role)
        except (ValueError, sqlite3.IntegrityError) as error:
            raise click.ClickException(str(error))
        click.echo('User created.')

    with app.app_context():
        g.app_database = app.config['DATABASE']
        init_db()
        db = get_db()
        for role in ROLES:
            username = os.environ.get(f'{role.upper()}_USERNAME')
            password = os.environ.get(f'{role.upper()}_PASSWORD')
            if bool(username) != bool(password):
                raise RuntimeError(f'Set both {role.upper()}_USERNAME and {role.upper()}_PASSWORD, or neither.')
            if username:
                existing = db.execute('SELECT role FROM users WHERE username=?', (username,)).fetchone()
                if existing and existing['role'] != role:
                    raise RuntimeError('Bootstrap usernames must be distinct for each role.')
                if not existing:
                    create_user(username, password, role)
        if app.config['DEMO_MODE']:
            seed_demo()
    return app


if __name__ == '__main__':
    # Flask's local development server, never use this server for production.
    create_app().run(host='127.0.0.1', port=5000, debug=False)
