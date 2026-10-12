# OfficeEMS - Flask portfolio project

A browser version of the Office Employee Management System V2 desktop project.
It runs on Python 3.10+ with Flask, server-rendered HTML and SQLite. No frontend
build or external email service is needed. All initial employee data is fake.

## Important: demo, not a real HR system

**Render Free does not preserve SQLite changes.** Its filesystem is ephemeral:
changes are lost when the service sleeps, restarts or redeploys. Free services
sleep after 15 minutes without inbound traffic and can take about a minute to
wake. This project is suitable for a portfolio demonstration, not real employee
records. The UI displays this warning. A rebuilt database starts again with
synthetic employees and the accounts supplied through environment variables.

Password changes work and remain saved while the SQLite database remains intact.
On Render Free, database loss also resets login passwords to the bootstrap
passwords in Render's environment settings. For durable use, replace SQLite with
a persistent database (and update database access), or use a paid service with a
persistent disk and set DATABASE_PATH to that disk. Turning DEMO_MODE off does
not make Render Free storage persistent. Never put real employee data in this demo.

Official Render sources, checked 12 October 2026:
- https://render.com/docs/deploy-flask
- https://render.com/docs/free

## Features and role permissions

| Feature | Admin | HR | Manager |
| --- | --- | --- | --- |
| Dashboard, employees and attendance | Yes | Yes | Read-only |
| Add / edit / delete employee | Yes | Yes | No |
| Mark or update attendance | Yes | Yes | No |
| Employee salaries and payroll | Yes | Yes | No |
| Employee and attendance CSV exports | Yes | Yes | Yes, salary excluded |
| Payroll CSV export | Yes | Yes | No |
| Change own password / logout | Yes | Yes | Yes |

The desktop app did not enforce role permissions. This is a deliberate web
policy: Admin and HR manage records, Manager reads records but cannot see salary
or payroll. Users are created through environment variables or the CLI, not a
public signup page. There is no department-scoped Manager permission model.
Payroll is only a record: it does not send money, compute taxes, or prorate pay.
CSV export includes all records, not only a search-filtered subset.

## 1. Run locally

Open a terminal inside this folder.

```bash
python -m venv .venv
```

Activate the environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows Command Prompt (alternative)
.venv\Scripts\activate.bat
# macOS / Linux (alternative)
source .venv/bin/activate
```

Then install:

```bash
pip install -r requirements.txt
```

Generate a random session secret locally:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Set SECRET_KEY in this terminal. Keep the generated value private. In PowerShell:

```powershell
$env:SECRET_KEY = Read-Host "Paste your locally generated session secret"
$env:COOKIE_SECURE = "false"
$env:DEMO_MODE = "true"
```

macOS / Linux alternative (read keeps the value out of shell history):

```bash
read -r -s -p "Paste your locally generated session secret: " SECRET_KEY
export SECRET_KEY
export COOKIE_SECURE=false
export DEMO_MODE=true
```

Create your account. The password prompt is hidden and asks for confirmation:

```bash
flask --app app:create_app create-user
```

Choose a username, role Admin, and a unique password of 12-128 characters. Repeat
this command with HR or Manager if you want to demonstrate those roles. There
are no default credentials. Finally run:

```bash
flask --app app:create_app run
```

Open http://127.0.0.1:5000 and sign in with the account you just created.
The `.env.example` file documents settings; copying it to `.env` does not load it
automatically with the supplied dependencies. Use terminal environment variables.
On Windows Command Prompt, use `set SECRET_KEY=...` for your generated secret.
The local database is created at an absolute path in `instance/office_ems.db`
and is ignored by Git. Closing and reopening the local app preserves saved
records, even when launched from a different working directory. If DATABASE_PATH
is relative, it is pinned to the project folder rather than the shell directory.
The desktop data-loss report could be caused by its relative DB filename;
this web version removes that ambiguity. Moving/deleting the database or using
Render Free still has the limitations explained above.
Do not reuse or copy the original desktop database: it uses plaintext passwords
and lacks the web app's session-version column. No desktop DB migration is included.

## 2. Deploy on Render Free

1. Create a GitHub repository and upload this folder's contents. `app.py`,
   `wsgi.py`, `requirements.txt`, `schema.sql`, `templates/` and `static/` must be
   at the repository root. Do not upload `.env`, databases, or `.venv`.
2. Sign in to Render, choose **New > Web Service**, and connect that repository.
3. Choose the Python runtime and the **Free** instance type. Leave Root Directory
   blank if the files are at the repository root.
4. Set **Build Command** to `pip install -r requirements.txt`.
5. Set **Start Command** to
   `gunicorn --workers 1 --bind 0.0.0.0:$PORT wsgi:app`.
6. In Render's environment settings, set:
   - `SECRET_KEY`: a random secret generated locally as above, at least 32 characters.
   - `ADMIN_USERNAME`: the login username you choose, 3-40 letters, numbers, `_`, `.` or `-`.
   - `ADMIN_PASSWORD`: your unique password, 12-128 characters. Do not use a real account's password.
   - `COOKIE_SECURE`: `true` (Render serves the public app over HTTPS).
   - `DEMO_MODE`: `true`.
   - Optional: `HR_USERNAME` + `HR_PASSWORD`, and/or `MANAGER_USERNAME` +
     `MANAGER_PASSWORD`. Use different usernames for every role. Both values in
     a pair are required; omit the pair if not needed.
7. Set Health Check Path to `/health` if shown. Deploy and wait for a successful
   build. Open the `onrender.com` address Render gives you.
8. Sign in using your Render Admin credentials. Check employee search, save one
   synthetic attendance record, generate payroll and download a CSV.
9. Open **Password**, verify your current password and set a new one. Log in again
   using the new password. On the current database the old password must fail.
10. Add the live URL to your portfolio only after checking it. Mention that it is
    a synthetic-data Flask demo. Do not publish Admin credentials in GitHub or
    on your resume. If a recruiter needs access, create a separate Manager demo
    account with a unique password and share it intentionally.

Alternative: Render's Blueprint flow can use the included `render.yaml`. It
requests the Admin username and password and generates the session secret.
Optional HR/Manager values can then be added in environment settings.

Changing a bootstrap password environment variable does **not** overwrite an
existing database user's password. Change it through the authenticated Password
page. Updating the environment variable is still useful on Render Free because
it defines that account's starting password after the ephemeral DB is lost.

## Password change fix

The original source called a plaintext column `password_hash` and compared the
submitted password directly in SQL. It did not include a password-change route.
This version uses Werkzeug's salted password hashes for account creation,
`check_password_hash` at login, and a dedicated authenticated password form:

1. Check the current password against the stored hash.
2. Validate new length, confirmation and that it differs from the old password.
3. Store a new hash in a committed SQLite transaction.
4. Increment the user's session version, invalidating previous sessions.
5. Clear the current session and require sign-in with the new password.

## Security and changes from Tkinter

- Browser routes and responsive templates replace all Tkinter windows.
- All pages have a restrained "Developed by Mohd Moaabia" footer. Admin
  accounts display "Mohd Moaabia" while retaining their chosen login username.
- Login/logout and all three roles are retained; role checks are server-side.
- No hardcoded credentials, email sending, SMTP secrets or default passwords.
- Synthetic seed names, reserved `example.invalid` emails and fictional addresses only.
- CSRF tokens protect every POST form, including login/logout. SQL uses parameters.
- Session cookies are HttpOnly/SameSite=Lax; set Secure on HTTPS deployments.
- Five failed attempts against a username cause a five-minute login cooldown.
  This small demo guard is not a full distributed anti-abuse system and can be
  used to temporarily lock out another username. Production needs stronger protection.
- Passwords are never logged or exported. Secrets belong in environment settings.
- Employee salary, date, foreign-key choices, unique codes/emails, attendance
  status and payroll amounts are validated. Blank emails become NULL so more
  than one employee can omit an email.
- Net pay uses decimal arithmetic, rounds to two decimals, and rejects negative net pay.
  SQLite stores salary amounts as REAL for compatibility with the original
  model; a production finance system should use integer minor units or DECIMAL.
- Saving attendance again updates the same employee/date record; payroll uses
  the same employee/month behavior.
- Deletion has a confirmation screen and cascades attendance/payroll cleanup.
- Dashboard "Present today" counts only today's attendance, not the desktop
  version's all-time present rows. "Pending payroll" counts all pending records.
- Dates use the hosting server's calendar date (Render generally uses UTC).
  Explicit date fields remain editable; timezone support is not included.
- CSV cells are escaped against spreadsheet formula injection; HTML is autoescaped.
- Local seed data is added only when there are no employees at startup. Deleting
  every employee and restarting in DEMO_MODE will repopulate the fake demo.
- No password reset email, audit log, master-data editor, public signup or actual
  payment processing is included. These are possible later project improvements.

## Project map

```text
app.py                    Routes, validation, authentication and database helpers
wsgi.py                   Production Gunicorn entry point
schema.sql                SQLite tables and constraints
requirements.txt          Flask and Gunicorn
render.yaml               Optional Render Blueprint
.env.example              Setting names only (no credentials)
templates/                Jinja HTML pages and reusable macros
static/style.css          Responsive styling (no external CDN)
tests/test_app.py         Automated route and security tests
README.md                 This guide
```

## Run automated tests

```bash
python -m unittest discover -s tests -v
```

The project was checked with Python 3.10, Flask 3.1 and Gunicorn 23.
Nine automated test cases passed. Tests use temporary databases and generate passwords at runtime. They cover login,
logout, form CSRF, password change and session revocation, all main pages,
employee CRUD/search, validation, attendance/payroll upserts, Manager/HR access,
CSV and HTML escaping, login cooldown and restart behavior.

## Troubleshooting

- **SECRET_KEY error:** export a random value at least 32 characters long before
  running Flask, tests, CLI commands or Gunicorn.
- **Cannot sign in on Render:** verify the Admin username and password environment
  settings and check deployment logs for invalid bootstrap settings. Local CLI
  accounts are not uploaded: the SQLite file is deliberately excluded.
- **Form expired:** reload the page, especially after login/logout in another tab.
- **No local session:** use `COOKIE_SECURE=false` for local HTTP.
- **Missing records after a Render restart:** expected on Free. See the storage warning.
- **Cold start or 429:** wait for the service to wake, or for the five-minute login
  cooldown to pass. Avoid repeated password guesses.
- **Need stable storage:** plan a persistent database before storing real information.
