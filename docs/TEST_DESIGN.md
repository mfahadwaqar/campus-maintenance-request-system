# Test design

How the Campus Maintenance Request System is tested, and why. The design follows the lectures
*6.1 Developer Testing* and *6.2 Developer Testing (code quality, BDD, browser)*.

**Result of the last full run:** 445 tests, all passing, on PostgreSQL. Application-code coverage
(line and branch): **89 %**.

## 1. What has to be true (scope)

The system exists so that **residents report faults, Call Center Staff assign them, technicians fix
them, and the ticket closes by itself**. The rules the professor's brief and OFAM's interviews put on
that workflow are the scope of the tests:

| Area | The rule |
|---|---|
| Roles and privacy | Three roles. A resident sees only their own tickets; a technician only jobs they currently hold; only Call Center Staff search and assign. Hidden data returns 404, not 403. |
| Intake | A request needs a valid category, building and room (dorm floors 1 to 4, rooms 01 to 10; villages SV01 to SV70) and a room confirmation. Photos are JPEG or PNG within size limits. |
| Review and assignment | Staff confirm the room, set a priority, and assign a unit (and optionally a technician in it). Staff can also enter a ticket for a caller, and assign a serious fault in one step. |
| Technician work | Start, hold (reason up to 400 characters plus a date), resume, complete with notes. Completion closes the ticket in the same step. |
| Closure and reopening | A resident or staff can reopen within **3 days** of completion, with a reason. After that it is refused. Comments are refused on a closed ticket. Rating is optional and never blocks closure. |
| Search and updates | Staff search by room, student ID and ticket number. New comments appear on open screens without a refresh. |
| API | Session login with CSRF, role-scoped JSON, optimistic locking (`version`), documented errors. |

## 2. Test types (lecture 6.1: "types of developer testing")

| Type | The question it answers | Tools | Where | Tests |
|---|---|---|---|---|
| **Unit** | Does one rule behave correctly in isolation? | pytest, `unittest.mock` | `tests/unit/` | 110 |
| **Component / Integration** | Do URL, view, ORM, database and login work together? | pytest-django, Django `Client` | `tests/integration/`, the Django tests in each app | 61 new + the 202 existing |
| **System / End-to-end** | Can a person finish the task in a real browser? | Playwright + `live_server`, Microsoft Edge | `tests/e2e/` | 10 |
| **Acceptance (BDD)** | Does it meet the stated business rule? Given / When / Then | pytest-bdd | `tests/bdd/` | 13 scenarios |
| **Regression** | Did a fixed bug come back? | The whole suite, run by GitLab CI; named regression tests | `tests/regression/` and the whole suite | 12 named + all |
| **Security** | Can it be attacked? | pytest, `Client(enforce_csrf_checks=True)` | `tests/security/` | 36 |
| **Performance** | Does it stay responsive as data grows? | `CaptureQueriesContext` | `tests/performance/` | 7 |
| **Reliability** | Does it survive failures and simultaneous users? | threads, `mock`, `transaction=True` | `tests/reliability/` | 5 |

The 202 tests that already existed in each Django app (`accounts/`, `reports/`, `assignments/`,
`notifications/`, `ps4/`) are kept and run by the same command. pytest-django runs them unchanged.

## 3. How the test cases were designed (lecture 6.1: "how we design tests")

| Approach | Meaning (from the lecture) | Used for | Tests |
|---|---|---|---|
| **White-box** | Design from the code: execute both outcomes of every branch and condition | status rules, services, room validation, progress line | 82 |
| **Black-box** | Design from requirements, inputs and visible outputs | photo upload, error pages, search, security attacks | 77 |
| **Grey-box** | Drive the public interface, then check the known database state | page journeys, concurrency, query counts | 32 |

Techniques applied:

| Technique | Example in this project |
|---|---|
| **Boundary values** | reopen window at 2 days 23 h 59 min (allowed) and 3 days 1 min (refused); hold reason 399, 400 (allowed), 401 (refused); rating 0, 1, 5, 6; room A110 vs A111, floor 4 vs 5; village SV01, SV70, SV71; photo size and pixel limits at the limit and one over |
| **Equivalence classes** | valid JPEG, valid PNG, other image formats, renamed text file, PNG renamed to .jpg |
| **Branch and condition testing** | priority required only when assigning from *under review*; technician must belong to the chosen unit; comment allowed unless closed; follow-up flag set by residents and cleared by staff |
| **Positive and negative pairs** | every rule has a "does it work?" test and a "does it fail safely?" test. Negative tests also assert the **database did not change** (status, version and history rows) |
| **Mocks and stubs** | the email sender is replaced: a *mock* checks it was called once with the right recipient; a *stub* makes it raise to prove a dead mail server does not stop a resident submitting |
| **Arrange, Act, Assert** | used in every test; BDD uses Given / When / Then |
| **Fixtures** | reusable users, buildings, a `flow` helper and ready-made tickets in `tests/conftest.py` |
| **Model-based** | the 14-row status rule table is tested as a model: four invariants (nothing leaves *rejected*, only the system closes, work statuses belong to the technician, only resident or staff reopen) plus illegal jumps |
| **Think like a user, a breaker, a maintainer** | user: the full journey; breaker: forged posts, hostile input, other people's tickets; maintainer: regression tests named after the defect they guard |

## 4. Requirements traceability

| Requirement (change-list number) | Tests |
|---|---|
| Auto-close on completion (#1) | unit `test_completion_closes_the_ticket_in_the_same_step…`; BDD "Completing a job closes the ticket"; E2E repair journey |
| Reopen within 3 days, with reason (#2, #15) | unit boundaries (inside, outside, setting); BDD 2-days and 4-days scenarios; integration; E2E "Reopen window open" |
| No 15-day closure job (#3) | regression R11 |
| Comments blocked when closed, allowed after reopen (#4) | unit; BDD; integration |
| Rating optional (#5) | unit `test_rating_boundaries` |
| Search by room, student ID, ticket (#6) | integration; BDD outline (4 examples); security (SQL-like input); regression R3 |
| Live updates (#7) | E2E "new comment appears without a refresh"; API `since` tests |
| Follow-ups linked to the ticket (#8) | unit `test_the_follow_up_flag_follows_who_wrote_last` |
| Serious fault in one action (#9) | BDD "Staff create and assign…"; `accounts/test_caller_entry.py` |
| Room check before issue (#10) | unit `test_review_needs_the_room_to_be_verified` |
| Hold with reason and date, resident notified (#11) | unit hold boundaries; BDD hold scenario; regression R1 |
| Unit results (#12) | `accounts/test_*`; regression R4 |
| Completion without the resident (#13) | unit `test_completion_without_the_resident_is_recorded_as_unsigned` |
| Completion notice leads with the outcome (#17) | unit `test_the_closing_notice_leads_with_the_outcome…` |
| Technician access limited to their jobs (#18) | security; integration role matrix and forged posts; regression R10 |
| Photos visible only to the allowed roles (#19) | integration `test_an_uploaded_photo_is_stored_and_only_visible…`; unit photo pipeline |
| Reference data loaded (#20) | `accounts/test_seed_demo.py`; regression R6 |
| Terminology and cleanup (#21, #22) | regression R12 (every role's pages contain no *Officer*, *Unit Staff*, *KPI*, *mobile app*, *15-day*, *master request*) |
| *Not built (optional P2):* second note (#14) | not applicable |

## 5. Beyond functional correctness (lecture 6.1 and 6.2)

**Security**: login required on every page; wrong password reveals nothing about which part was wrong;
no redirect to another site after login; session cookie not readable by scripts; every state-changing
page and API call rejects a missing CSRF token (7 pages plus the API); HTML in titles, descriptions and
comments is escaped on every page that shows it; SQL-like search text is treated as data; residents
cannot call staff or technician actions; *mass assignment* (sending `status`, `resident`, `ticket_no`,
`version`, `priority` when creating) is ignored; another resident or an unassigned technician gets 404 on
every ticket endpoint; passwords and hashes never appear in JSON; framing and sniffing headers set;
admin site closed to ordinary users.

**Performance**: the staff queue, resident list and API list run the **same number of queries for 2
tickets as for 16** (no N+1); pagination caps at 25 (pages) and 20 (API); a 40-ticket queue renders
within a smoke-test time budget. Wall-clock timing is unreliable on a shared machine, so query counts are
the stable measure.

**Reliability**: two staff acting on the same version at once, one wins and one gets a conflict (real
threads, real commits); a job cannot be completed twice at once; if closing fails, the completion is
rolled back too; if saving a photo fails no half-created ticket remains; a dead mail server does not
stop submission.

**Usability and accessibility** (browser only): the room checkbox sits beside its label; pages do not
scroll sideways at phone width (375 px); the light theme is used even when the system prefers dark; the
subcategory list follows the chosen category and clears a stale choice; all form fields are found by their
labels (the E2E tests use label and role locators, which fails if a label is missing).

## 6. Static analysis and coverage (lecture 6.2)

| Tool | What it checks | Result | Action |
|---|---|---|---|
| `manage.py check` | configuration, models, URLs | no issues | none |
| `manage.py check --deploy` (production settings) | insecure production settings | no security warnings; 7 API-documentation naming warnings | one fixed (type hint); enum naming left as a note |
| **Ruff** | probable coding errors | **127 findings before, 38 after** | safe fixes applied (unused imports, import order). 44 *RUF012* hits are Django's required class-level `Meta` lists, handled by a narrow documented exception in `ruff.toml`, as the lecture advises. The rest is style |
| **Radon** | cyclomatic complexity | average **A (3.5)**; one outlier: `reports/services.py::_apply_transition` = **F (71)**; seven functions at C | documented, **not refactored now**: it is the heart of the workflow. The tests in section 4 pin its behaviour, so it can be split safely later |
| **Bandit** | insecure code patterns | no issues in application code | none |
| **pip-audit** | known vulnerable packages | **Pillow 12.3.0: 42 advisories, fixed in 13.0.0** | upgraded to 13.0.0 (`requirements.txt`); photo tests pass |
| **pytest-cov** | which lines and branches ran | application code ****89 %****; before the error-path tests it was 87 % | read the *missing lines* and added 28 tests for the error branches of the staff, technician and resident pages |

Coverage is a diagnostic, not proof of quality (lecture). The remaining gaps are mostly defensive branches
inside `_apply_transition`, API validation messages, and `seed_room_locations`, a management command that
duplicates a migration and is never run.

## 7. Defects this testing found

| # | Found by | Defect | Status |
|---|---|---|---|
| D1 | integration journey (grey-box) | A resident who **verified** a ticket and then **reopened** it caused a database error (HTTP 500): one verification row is allowed per completed job. | **Fixed** in `reports/services.py` (reopen replaces the verification). Regression R2 |
| D2 | performance test | The staff queue ran **one extra query per ticket** (N+1), introduced when the unit name was added. | **Fixed** (`select_related`). Performance test keeps it fixed |
| D3 | security test | A search the form could not read (a ticket number over 30 characters) **silently listed every ticket**. | **Fixed**: no results and an error message. Regression R3 |
| D4 | pip-audit | Pillow 12.3.0 has 42 known advisories; Pillow processes residents' uploaded photos. | **Fixed** (13.0.0) |
| D5 | `check --deploy` | The API documentation could not describe the "unit" field of the current user. | **Fixed** |
| D6 | manual review | After putting work on hold, a technician could not resume it. | **Fixed**. Regression R1 |
| D7 | running the README steps | `seed_demo_data` crashed on a fresh database. | **Fixed**. Regression R6 |
| D8 | browser test | Subcategory list kept a stale choice after the category changed. | **Fixed**. Regression R7, E2E test |

Findings **not changed** (documented for the team):

* `_apply_transition` is too complex (F, 71). Refactor behind the existing tests.
* The written specification and the sequence diagrams differ from the code in three small ways: a new
  ticket has **version 1** (documents say 0); reopening writes **one** history row *Closed to Assigned* with
  the reason (diagram shows a separate *Reopened* row); ticket numbers look like `CMR-2026-<id>-000001`
  (documents say `MR-YYYY-NNNNNN`). Update the documents or the code.
* `seed_room_locations` is unused (0 % coverage).

## 8. What is not tested, and why

* Real email delivery and HTTPS cookies in production mode (need a mail server and TLS).
* Browsers other than Chromium-based Edge; mobile devices (only a 375 px viewport is emulated).
* Load beyond two simultaneous users; the performance tests are query-count based, not a load test.
* Automated accessibility auditing (such as axe); only label and role locators and layout are checked.
* Type checking with mypy: the project has almost no type annotations, so it would report noise.

## 9. How to run

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium     # only if Microsoft Edge is not installed; set E2E_BROWSER_CHANNEL= (empty)

pytest -q                                  # everything
pytest -m "not e2e"                        # without the browser tests (faster)
pytest -m unit                             # one type: unit, integration, security, performance,
                                           #   reliability, regression, bdd, e2e
pytest -m whitebox                         # or one design approach: whitebox, blackbox, greybox
pytest tests/bdd -v                        # the acceptance scenarios
pytest --cov=accounts --cov=reports --cov=assignments --cov=notifications --cov-branch --cov-report=term-missing

ruff check .                               # static checks
radon cc accounts reports assignments notifications -a -s
bandit -r accounts reports assignments notifications -x "*/tests*,*/test_*,*/migrations/*"
pip-audit -r requirements.txt
python manage.py check --deploy
```

GitLab CI (`.gitlab-ci.yml`) runs the same checks after every push: a **static** job, a **test** job (all
tests except the browser ones, with branch coverage) and an **e2e** job (browser tests), so every change
is a regression run.
