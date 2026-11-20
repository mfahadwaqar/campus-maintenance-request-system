# Campus Maintenance Request System

A Django web application for the Asian Institute of Technology's Office of Facilities and Asset
Management (OFAM). Residents report faults in their rooms, Call Center Staff review and assign
them to a unit, and the Technician/Contractor completes the work. The ticket closes when the job
is completed, and the resident can reopen it for 3 days.

- **Pages:** server-rendered Django templates (the front end).
- **REST API:** Django REST Framework under `/api/`, documented at `/api/docs/`.
- **Database:** PostgreSQL.
- **Research pages (problem set 3):** under `/ps4/`.

## Roles

| Role | Stored value | What they do |
|---|---|---|
| Resident | `RESIDENT` | submit requests, comment, verify finished work, reopen within 3 days |
| Call Center Staff | `CALL_CENTER_STAFF` | queue and search, review, assign, reject, enter requests for callers, reopen |
| Technician/Contractor | `TECHNICIAN_CONTRACTOR` | start, hold, resume and complete assigned jobs |
| Administrator | `is_staff`, no role | manage data in `/admin/` |

## Run it locally

Requirements: Python 3.13 or newer, Git, and PostgreSQL 17 (Docker is the easiest way to get it).

**1. Get the code**

```bash
git clone https://gitlab.com/fullstack-ait-2026/merge-conflict/campus-maintainance-request-system.git
cd campus-maintainance-request-system
git checkout feature/frontend
```

**2. Create a virtual environment and install packages**

```bash
python -m venv .venv
# Windows PowerShell:   .venv\Scripts\Activate.ps1
# Windows Git Bash:     source .venv/Scripts/activate
# macOS / Linux:        source .venv/bin/activate
pip install -r requirements.txt
```

**3. Start PostgreSQL** (any PostgreSQL 17 works; this is the Docker way)

```bash
docker run -d --name campus-db -p 5432:5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=localpass \
  -e POSTGRES_DB=campus-maintainance-request-system postgres:17-alpine
```

**4. Create your `.env`**

```bash
cp .env.example .env        # on PowerShell: Copy-Item .env.example .env
```

Edit `.env` and set:

```
POSTGRES_PASSWORD=localpass        # the password you used in step 3
DJANGO_SECRET_KEY=any-long-random-text
DEMO_USER_PASSWORD=Choose-A-Demo-Password-1
```

`.env` is ignored by Git. The settings read it automatically.

**5. Create the tables and load the data.** Run these in this order:

```bash
python manage.py migrate
python manage.py seed_reference_data           # categories and subcategories
python manage.py seed_campus_reference_data    # dorm and village buildings, units
python manage.py seed_demo_data                # demo accounts and sample tickets
python manage.py createsuperuser               # your own admin account
```

**6. Start the app**

```bash
python manage.py runserver
```

Open http://localhost:8000/login/ and log in with the **username** from the table below.

### Demo accounts

The password for every demo account is the `DEMO_USER_PASSWORD` you put in `.env`.

| Role | Usernames |
|---|---|
| Resident | `demo_resident_01` to `demo_resident_04` |
| Call Center Staff | `demo_officer_01`, `demo_officer_02` |
| Technician/Contractor | `demo_technician_01` and `04` (Technical Services), `02` (Pest Control), `03` (Accommodation) |
| Administrator | the account you created with `createsuperuser`, at `/admin/` |

The seed also creates six sample tickets in different states (submitted, under review, assigned,
in progress and closed). The closed one is inside its 3-day reopen window.

### Useful addresses

| Address | What |
|---|---|
| `/login/` | sign in |
| `/admin/` | administration (administrator account) |
| `/api/docs/` | REST API documentation (Swagger) |
| `/ps4/` | research pages for problem set 3 |
| `/health/` | health check |

Email is printed in the terminal while running locally. Nothing is sent.

## Run the tests

```bash
pip install -r requirements-dev.txt          # test and code-quality tools
pytest -q                                    # all tests (about 440, roughly 10 minutes)
pytest -m "not e2e"                          # without the browser tests
pytest -m unit                               # one type; also: integration, security, performance,
                                             #   reliability, regression, bdd, e2e
python manage.py test                        # the Django runner still works for the older tests
```

PostgreSQL must be running, and the database user needs permission to create a test database
(the `postgres` user does). The browser tests drive Microsoft Edge if it is installed. Otherwise run
`python -m playwright install chromium` and set `E2E_BROWSER_CHANNEL=` (empty).

How the tests were designed, which lecture technique each one uses, the static-analysis results and
the defects found are in [docs/TEST_DESIGN.md](docs/TEST_DESIGN.md). A short manual checklist is in
[TESTING.md](TESTING.md).

## REST API in short

- Sign in: `GET /accounts/csrf/`, then `POST /api/auth/login/` with `{"email", "password"}` and the
  `X-CSRFToken` header. Who is signed in: `GET /api/auth/me/`. Sign out: `POST /api/auth/logout/`.
- Reports: list and create, detail, status, assign, verify, reopen, comments, history, photos.
- Staff-only search on the report list: `ticket_no`, `student_id`, `room`.
- Reference lists: buildings, room locations, categories, units. Unit results: `/api/units/results/`.

Every refusal is a JSON body. Conflict codes: `version_conflict`, `ticket_closed`,
`reopen_window_closed`, `ticket_not_closed`. Open `/api/docs/` for every field and response.

## Deploying

Set these environment variables on the server (see `.env.example`): `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, the `POSTGRES_*` settings and `FRONTEND_ORIGINS` (allowed browser
origins for the API). Then run `migrate`, `seed_reference_data` and `seed_campus_reference_data`.

The production settings force secure cookies. If the server is served over plain `http`, set
`DJANGO_COOKIE_SECURE=false` or logins will not stick. Prefer https.

`docker-compose.yml` and the `nginx/` folder describe the server setup.

For a free deployment on Render with a Neon database (photos are kept in the database), follow
[docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md).

## Notes

- Student Village room codes (for example `SV04A1`) are accepted in a provisional format that
  OFAM has not yet confirmed.
- Closing a ticket happens automatically when the technician completes it. There is no 15-day
  closure rule and no staff closure step.
- Photos are checked, re-encoded and stored privately. They are only visible to the people the
  permission rules allow.
