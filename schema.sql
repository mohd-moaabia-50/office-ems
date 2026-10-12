
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                session_version INTEGER NOT NULL DEFAULT 1,
                role TEXT NOT NULL CHECK(role IN ('Admin','HR','Manager'))
            );

            CREATE TABLE IF NOT EXISTS departments (
                dept_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dept_name TEXT UNIQUE NOT NULL,
                location TEXT
            );

            CREATE TABLE IF NOT EXISTS designations (
                designation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL,
                grade TEXT
            );

            CREATE TABLE IF NOT EXISTS employees (
                emp_id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_code TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                dept_id INTEGER NOT NULL,
                designation_id INTEGER NOT NULL,
                phone TEXT,
                email TEXT UNIQUE,
                join_date TEXT NOT NULL,
                salary REAL NOT NULL,
                employment_status TEXT NOT NULL DEFAULT 'Active',
                address TEXT,
                FOREIGN KEY (dept_id) REFERENCES departments(dept_id) ON UPDATE CASCADE,
                FOREIGN KEY (designation_id) REFERENCES designations(designation_id) ON UPDATE CASCADE
            );

            CREATE TABLE IF NOT EXISTS attendance (
                attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_id INTEGER NOT NULL,
                att_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('Present','Absent','Leave','WFH')),
                remarks TEXT,
                UNIQUE(emp_id, att_date),
                FOREIGN KEY (emp_id) REFERENCES employees(emp_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payroll (
                payroll_id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_id INTEGER NOT NULL,
                pay_month TEXT NOT NULL,
                basic_salary REAL NOT NULL,
                allowance REAL DEFAULT 0,
                deduction REAL DEFAULT 0,
                net_salary REAL NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'Pending',
                UNIQUE(emp_id, pay_month),
                FOREIGN KEY (emp_id) REFERENCES employees(emp_id) ON DELETE CASCADE
            );
            
CREATE TABLE IF NOT EXISTS login_attempts (
    username TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    started_at INTEGER NOT NULL
);
